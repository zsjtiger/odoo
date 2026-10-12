"""Optimizations of the conditions on the dates, the datetimes and the properties."""

from __future__ import annotations

import typing
import warnings
from datetime import date, datetime, time, timedelta, timezone, UTC
from odoo.tools import OrderedSet
from odoo.tools.date_utils import parse_date, parse_iso_date
from odoo.orm.core.utils import COLLECTION_TYPES

if typing.TYPE_CHECKING:
    pass

from ..classes import DomainCondition, DomainOr, _FALSE_DOMAIN
from ..constants import OptimizationLevel
from ..registry import field_type_optimization

def _value_to_date(value, env, iso_only=False):
    # check datetime first, because it's a subclass of date
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) or value is False:
        return value
    if isinstance(value, str):
        if iso_only:
            try:
                value = parse_iso_date(value)
            except ValueError:
                # check format
                parse_date(value, env)
                return value
        else:
            value = parse_date(value, env)
        return _value_to_date(value, env)
    if isinstance(value, COLLECTION_TYPES):
        return OrderedSet(_value_to_date(v, env=env, iso_only=iso_only) for v in value)
    raise ValueError(f'Failed to cast {value!r} into a date')


@field_type_optimization(['date'])
def _optimize_type_date(condition, model):
    """Make sure we have a date type in the value"""
    operator = condition.operator
    if (
        operator not in ('in', 'not in', '>', '<', '<=', '>=')
        or "." in condition.field_expr
    ):
        return condition
    value = _value_to_date(condition.value, model.env, iso_only=True)
    if value is False and operator[0] in ('<', '>'):
        # comparison to False results in an empty domain
        return _FALSE_DOMAIN
    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(['date'], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_type_date_relative(condition, model):
    operator = condition.operator
    if (
        operator not in ('in', 'not in', '>', '<', '<=', '>=')
        or "." in condition.field_expr
        or not isinstance(condition.value, (str, OrderedSet))
    ):
        return condition
    value = _value_to_date(condition.value, model.env)
    return DomainCondition(condition.field_expr, operator, value)


def _value_to_datetime(value, env, iso_only=False):
    """Convert a value(s) to datetime.

    :returns: A tuple containing the converted value and a boolean indicating
              that all input values were dates.
              These are handled differently during rewrites.
    """
    if value is False:
        return False, True

    if isinstance(value, datetime):
        if value.tzinfo:
            # cast to a naive datetime
            warnings.warn("Use naive datetimes in domains")
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value, False
    if isinstance(value, str):
        if iso_only:
            try:
                value = parse_iso_date(value)
            except ValueError:
                # check formatting
                _dt, is_date = _value_to_datetime(parse_date(value, env), env)
                return value, is_date
        else:
            value = parse_date(value, env)
        return _value_to_datetime(value, env)
    if isinstance(value, date):
        value = datetime.combine(value, time.min)
        if value.year not in (1, 9999) and env.tz != UTC:
            value = value.replace(tzinfo=env.tz) \
                .astimezone(timezone.utc) \
                .replace(tzinfo=None)
        return value, True
    if isinstance(value, COLLECTION_TYPES):
        value, is_date = zip(*(_value_to_datetime(v, env=env, iso_only=iso_only) for v in value))
        return OrderedSet(value), all(is_date)
    raise ValueError(f'Failed to cast {value!r} into a datetime')


@field_type_optimization(['datetime'])
def _optimize_type_datetime(condition, model):
    """Make sure we have a datetime type in the value"""
    field_expr = condition.field_expr
    operator = condition.operator
    if (
        operator not in ('in', 'not in', '>', '<', '<=', '>=')
        or "." in field_expr
    ):
        return condition
    value, is_date = _value_to_datetime(condition.value, model.env, iso_only=True)

    # Handle inequality
    if operator[0] in ('<', '>'):
        if value is False:
            return _FALSE_DOMAIN
        if not isinstance(value, datetime):
            return condition
        if value.microsecond:
            assert not is_date, "date don't have microseconds"
            value = value.replace(microsecond=0)
        delta = timedelta(days=1) if is_date else timedelta(seconds=1)
        if operator == '>':
            try:
                value += delta
            except OverflowError:
                # higher than max, not possible
                return _FALSE_DOMAIN
            operator = '>='
        elif operator == '<=':
            try:
                value += delta
            except OverflowError:
                # lower than max, just check if field is set
                return DomainCondition(field_expr, '!=', False)
            operator = '<'

    # Handle equality: compare to the whole second
    if (
        operator in ('in', 'not in')
        and isinstance(value, COLLECTION_TYPES)
        and any(isinstance(v, datetime) for v in value)
    ):
        delta = timedelta(seconds=1)
        domain = DomainOr.apply(
            DomainCondition(field_expr, '>=', v.replace(microsecond=0))
            & DomainCondition(field_expr, '<', v.replace(microsecond=0) + delta)
            if isinstance(v, datetime) else DomainCondition(field_expr, '=', v)
            for v in value
        )
        if operator == 'not in':
            domain = ~domain
        return domain

    return DomainCondition(field_expr, operator, value)


@field_type_optimization(['datetime'], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_type_datetime_relative(condition, model):
    operator = condition.operator
    if (
        operator not in ('in', 'not in', '>', '<', '<=', '>=')
        or "." in condition.field_expr
        or not isinstance(condition.value, (str, OrderedSet))
    ):
        return condition
    value, _ = _value_to_datetime(condition.value, model.env)
    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(['properties'], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_properties_date_datetime(condition, model):
    operator = condition.operator
    if (
        operator not in ('in', 'not in', '>', '<', '<=', '>=')
        or condition.field_expr.count('.') != 1
        or not isinstance(condition.value, (str, OrderedSet))
    ):
        return condition
    definition = model.get_property_definition(condition.field_expr)
    property_type = definition.get("type")

    if property_type == 'date':
        value = _value_to_date(condition.value, model.env)
    elif property_type == 'datetime':
        value, _ = _value_to_datetime(condition.value, model.env)
    else:
        return condition
    # we need to serialize the value as a string to be able to use with properties
    if isinstance(value, COLLECTION_TYPES):
        value = OrderedSet(
            str(item) if isinstance(item, (date, datetime)) else item
            for item in value
        )
    elif isinstance(value, (date, datetime)):
        value = str(value)

    return DomainCondition(condition.field_expr, operator, value)

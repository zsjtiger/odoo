"""Optimizations of the conditions on sets of values, and of the selection and boolean fields."""

from __future__ import annotations

import logging
import typing
import warnings
from odoo.tools import SQL, OrderedSet, str2bool
from odoo.orm.core.utils import COLLECTION_TYPES

if typing.TYPE_CHECKING:
    pass

from ..base import ANY_TYPES
from ..boolean import _FALSE_DOMAIN, _TRUE_DOMAIN
from ..condition import DomainCondition
from ..constants import OptimizationLevel, _INVERSE_OPERATOR
from ..registry import field_type_optimization, operator_optimization

_logger = logging.getLogger('odoo.domains')


@operator_optimization(['=?'])
def _operator_equal_if_value(condition, _):
    """a =? b  <=>  not b or a = b"""
    if not condition.value:
        return _TRUE_DOMAIN
    return DomainCondition(condition.field_expr, '=', condition.value)


@operator_optimization(['=', '!='])
def _operator_equal_as_in(condition, _):
    """ Equality operators.

    Validation for some types and translate collection into 'in'.
    """
    value = condition.value
    operator = 'in' if condition.operator == '=' else 'not in'
    if isinstance(value, COLLECTION_TYPES):
        if not value:  # views sometimes use ('user_ids', '!=', []) to indicate the user is set
            _logger.warning("The domain condition %r should compare with False.", condition)
            value = OrderedSet([False])
        else:
            _logger.warning("The domain condition %r should use the 'in' or 'not in' operator.", condition)
            value = OrderedSet(value)
    elif isinstance(value, SQL):
        # transform '=' SQL("x") into 'in' SQL("(x)")
        value = SQL("(%s)", value)
    else:
        value = OrderedSet((value,))
    return DomainCondition(condition.field_expr, operator, value)


@operator_optimization(['in', 'not in'])
def _optimize_in_set(condition, _model):
    """Make sure the value is an OrderedSet or use 'any' operator"""
    value = condition.value
    if isinstance(value, OrderedSet) and value:
        # very common case, just skip creation of a new Domain instance
        return condition
    if isinstance(value, ANY_TYPES):
        operator = 'any' if condition.operator == 'in' else 'not any'
        return DomainCondition(condition.field_expr, operator, value)
    if not value:
        return _FALSE_DOMAIN if condition.operator == 'in' else _TRUE_DOMAIN
    if not isinstance(value, COLLECTION_TYPES):
        # TODO show warning, note that condition.field_expr in ('group_ids', 'user_ids') gives a lot of them
        _logger.debug("The domain condition %r should have a list value.", condition)
        value = [value]
    return DomainCondition(condition.field_expr, condition.operator, OrderedSet(value))


@operator_optimization(['in', 'not in'])
def _optimize_in_required(condition, model):
    """Remove checks against a null value for required fields."""
    value = condition.value
    field = condition._field(model)
    if (
        field.falsy_value is None
        and (
            (field.required and field in model.env.registry.not_null_fields)
            or field.name == 'id'
        )
        # only optimize if there are no NewId's
        and all(model._ids)
    ):
        value = OrderedSet(v for v in value if v is not False)
    if len(value) == len(condition.value):
        return condition
    return DomainCondition(condition.field_expr, condition.operator, value)


@field_type_optimization(['boolean'])
def _optimize_boolean_in(condition, model):
    """b in boolean_values"""
    value = condition.value
    operator = condition.operator
    if operator not in ('in', 'not in') or not isinstance(value, COLLECTION_TYPES):
        condition._raise("Cannot compare %r to %s which is not a collection of length 1", condition.field_expr, type(value))
    if not all(isinstance(v, bool) for v in value):
        # parse the values
        warnings.warn(f"Since 20.0, compare booleans only with booleans in {condition!r}", DeprecationWarning)
        value = {
            str2bool(v.lower(), False) if isinstance(v, str) else bool(v)
            for v in value
        }
    if len(value) == 1 and not any(value):
        # when comparing boolean values, always compare to [True] if possible
        # it eases the implementation of search methods
        operator = _INVERSE_OPERATOR[operator]
        value = [True]
    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(['selection'], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_type_selection(condition, model):
    """Transform expressions like `(field, 'not in', excl)` into `(field, 'in', incl)`.
    This may lead to better performance if `field` is indexed.
    """
    field = condition._field(model)
    if (
        condition.operator != 'not in'
        or '.' in condition.field_expr
        or field._selection is None
        or not any(condition.value)  # not in [False] should remain like that
    ):
        return condition
    excluded = condition.value
    included = OrderedSet([*field._selection, False]) - excluded
    return DomainCondition(condition.field_expr, 'in', included)

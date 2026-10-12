# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Recordset operations: sorting and filtering the records, and the order of the sorts."""

from __future__ import annotations

import functools
import re
import typing
from collections.abc import Callable

import psycopg2.errors
import psycopg2.extensions



from odoo.orm.core.domains import Domain

from odoo.orm.core.utils import (
    ReversibleComparator,
)

from collections import defaultdict
from operator import itemgetter
if typing.TYPE_CHECKING:
    from typing import Self
    from odoo.orm.core.types import DomainType


regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")

from odoo.orm.models import BaseModel


def sort(self, key: Callable[[Self], typing.Any] | str | None=None, reverse: bool=False) -> Self:
    if len(self) < 2:
        return self
    if isinstance(key, str):
        key = self._sorted_order_to_function(key)
    elif key is None:
        key = self._sorted_order_to_function(self._order)
    ids = tuple(item.id for item in sorted(self, key=key, reverse=reverse))
    return self.__class__(self.env, ids, self._prefetch_ids)


def _sorted_order_to_function(self, order: str) -> Callable[[BaseModel], tuple]:
    def order_to_function(order_part):
        order_match = regex_order.match(order_part)
        if not order_match:
            raise ValueError(f"Invalid order {order!r} to sort")
        field_name = order_match['field']
        property_name = order_match['property']
        reverse = (order_match['direction'] or '').upper() == 'DESC'
        nulls = (order_match['nulls'] or '').upper()
        if nulls:
            nulls_first = nulls == 'NULLS FIRST'
        else:
            nulls_first = reverse

        field = self._fields[field_name]
        field_expr = f'{field_name}.{property_name}' if property_name else field_name
        if field.type == 'many2one' and (not property_name or property_name == 'id'):
            seen = self.env.context.get('__m2o_order_seen_sorted', ())
            if field in seen:
                return lambda _: None
            comodel = self.env[field.comodel_name].with_context(__m2o_order_seen_sorted=frozenset((field, *seen)))
            func_comodel = comodel._sorted_order_to_function(property_name or comodel._order)

            def getter(rec):
                value = rec[field_name]
                if not value:
                    return None
                return func_comodel(value)
        elif field.relational:
            raise ValueError(f"Invalid order on relational field {order_part!r} to sort")
        elif field.type == 'boolean':
            getter = field.expression_getter(field_expr)
        else:
            raw_getter = field.expression_getter(field_expr)

            def getter(rec):
                value = raw_getter(rec)
                return value if value is not False else None

        comparator = functools.partial(
            ReversibleComparator,
            reverse=reverse,
            none_first=nulls_first,
        )
        return lambda rec: comparator(getter(rec))

    item_makers = [
        order_to_function(order_part)
        for order_part in order.split(',')
    ]
    return lambda rec: tuple(fn(rec) for fn in item_makers)


def filtered(self, func: str | Callable[[Self], bool] | Domain) -> Self:
    if not func:
        # align with mapped()
        return self

    if callable(func):
        # normal function
        pass
    elif isinstance(func, str):
        if '.' in func:
            seq_fnames = func
            func = lambda record: any(record.mapped(seq_fnames))  # noqa: E731
        else:
            # avoid costly mapped
            func = self._fields[func].__get__
    elif isinstance(func, Domain):
        return self.filtered_domain(func)
    else:
        raise TypeError(f"Invalid function {func!r} to filter on {self._name}")

    ids = tuple(id_ for id_, rec in zip(self._ids, self) if func(rec))
    return self.__class__(self.env, ids, self._prefetch_ids)


def filtered_domain(self, domain: DomainType) -> Self:
    if not self or not domain:
        return self
    predicate = Domain(domain)._as_predicate(self)
    ids = tuple(id_ for id_, rec in zip(self._ids, self) if predicate(rec))
    return self.__class__(self.env, ids, self._prefetch_ids)


def mapped[T](self, func: str | Callable[[Self], T]) -> list | BaseModel:
    if not func:
        return self                 # support for an empty path of fields

    if isinstance(func, str):
        # special case: sequence of field names
        *rel_field_names, field_name = func.split('.')
        records = self
        for rel_field_name in rel_field_names:
            records = records[rel_field_name]
        field = records._fields[field_name]
        getter = field.__get__
        if field.relational:
            # union of records
            return getter(records)
        return [getter(record) for record in records]

    if self:
        vals = [func(rec) for rec in self]
        if isinstance(vals[0], BaseModel):
            return vals[0].browse().union(vals)
        return vals
    else:
        # we want to follow-up the comodel from the function
        # so we pass an empty recordset
        vals = func(self)
        return vals if isinstance(vals, BaseModel) else []


def grouped[T](self, key: str | Callable[[Self], T]) -> dict[typing.Any, Self]:
    if isinstance(key, str):
        key = itemgetter(key)

    collator = defaultdict(list)
    for record in self:
        collator[key(record)].extend(record._ids)

    browse = functools.partial(type(self), self.env, prefetch_ids=self._prefetch_ids)
    return {key: browse(tuple(ids)) for key, ids in collator.items()}

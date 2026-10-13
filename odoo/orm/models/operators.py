# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Operators of the recordsets: the set operations and the comparisons of the records."""

from __future__ import annotations

import logging
import re
import typing
import warnings

import psycopg2.extensions

from odoo.tools.text.translate import LazyTranslate



from odoo.orm.core.utils import Prefetch

if typing.TYPE_CHECKING:
    from typing import Self


_lt = LazyTranslate('base')
_logger = logging.getLogger('odoo.models')
_unlink = logging.getLogger('odoo.models.unlink')

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



def add(self, other) -> Self:
    try:
        if other._name != self._name:
            raise TypeError(f"inconsistent models in: {self} + {other}")
        if other:
            ids = self._ids + other._ids
            return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids, other._prefetch_ids))
    except AttributeError:
        raise TypeError(f"unsupported operand types in: {self} + {other!r}")
    return self


def sub(self, other) -> Self:
    try:
        if self._name != other._name:
            raise TypeError(f"inconsistent models in: {self} - {other}")
        other_ids = set(other._ids)
        ids = tuple(id_ for id_ in self._ids if id_ not in other_ids)
        return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids))
    except AttributeError:
        raise TypeError(f"unsupported operand types in: {self} - {other!r}")


def and_(self, other) -> Self:
    try:
        if self._name != other._name:
            raise TypeError(f"inconsistent models in: {self} & {other}")
        other_ids = set(other._ids)
        ids = tuple({id_: None for id_ in self._ids if id_ in other_ids})
        return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids))
    except AttributeError:
        raise TypeError(f"unsupported operand types in: {self} & {other!r}")


def or_(self, other) -> Self:
    try:
        if other._name != self._name:
            raise TypeError(f"inconsistent models in: {self} | {other}")
        if other:
            ids = tuple(dict.fromkeys(self._ids + other._ids))
            return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids, other._prefetch_ids))
    except AttributeError:
        raise TypeError(f"unsupported operand types in: {self} | {other!r}")
    return self


def eq(self, other):
    try:
        return self._name == other._name and set(self._ids) == set(other._ids)
    except AttributeError:
        if other:
            warnings.warn(f"unsupported operand type(s) for \"==\": '{self._name}()' == '{other!r}'", stacklevel=2)
    return NotImplemented


def lt(self, other):
    try:
        if self._name == other._name:
            return set(self._ids) < set(other._ids)
    except AttributeError:
        pass
    return NotImplemented


def le(self, other):
    try:
        if self._name == other._name:
            # these are much cheaper checks than a proper subset check, so
            # optimise for checking if a null or singleton are subsets of a
            # recordset
            if not self or self in other:
                return True
            return set(self._ids) <= set(other._ids)
    except AttributeError:
        pass
    return NotImplemented


def gt(self, other):
    try:
        if self._name == other._name:
            return set(self._ids) > set(other._ids)
    except AttributeError:
        pass
    return NotImplemented


def ge(self, other):
    try:
        if self._name == other._name:
            if not other or other in self:
                return True
            return set(self._ids) >= set(other._ids)
    except AttributeError:
        pass
    return NotImplemented

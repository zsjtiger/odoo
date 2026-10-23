# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Sequence protocol of the recordsets: iteration, indexing, length, truth and representation."""

from __future__ import annotations

import logging
import re
import typing

import psycopg2.extensions

from odoo.tools.misc import ReversedIterable
from odoo.tools.text.translate import LazyTranslate



from odoo.orm.core.utils import Prefetch

from odoo.orm.models import BaseModel
if typing.TYPE_CHECKING:
    from collections.abc import Iterator
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



def iterate(self) -> Iterator[Self]:
    ids = self._ids
    size = len(ids)
    if size <= 1:
        # detect and handle small recordsets (single `1f`)
        # early return if no records and avoid allocation if we have a one
        if size == 1:
            yield self
        return
    cls = self.__class__
    env = self.env
    prefetch_ids = self._prefetch_ids
    for id_ in ids:
        yield cls(env, (id_,), prefetch_ids)


def reversed_records(self) -> Iterator[Self]:
    # same as __iter__ but reversed
    ids = self._ids
    size = len(ids)
    if size <= 1:
        if size == 1:
            yield self
        return
    cls = self.__class__
    env = self.env
    prefetch_ids = ReversedIterable(self._prefetch_ids)
    for id_ in reversed(ids):
        yield cls(env, (id_,), prefetch_ids)


def contains(self, item: BaseModel | str) -> bool:
    try:
        if self._name == item._name:
            return len(item) == 1 and item.id in self._ids
        raise TypeError(f"inconsistent models in: {item} in {self}")
    except AttributeError:
        if isinstance(item, str):
            return item in self._fields
        raise TypeError(f"unsupported operand types in: {item!r} in {self}")


def getitem(self, key):
    if isinstance(key, str):
        # important: one must call the field's getter
        return self._fields[key].__get__(self)
    if isinstance(key, slice):
        ids = self._ids[key]
        prefetch_ids = Prefetch.union(ids, self._prefetch_ids)
    else:
        ids = (self._ids[key],)
        prefetch_ids = self._prefetch_ids
    return self.__class__(self.env, ids, prefetch_ids)


def setitem(self, key: str, value: typing.Any):
    # important: one must call the field's setter
    return self._fields[key].__set__(self, value)


def length(self) -> int:
    return len(self._ids)


def truth(self) -> bool:
    return True if self._ids else False  # fast version of bool(self._ids)


def to_int(self) -> int:
    return self.id or 0


def hash_ids(self):
    return hash((self._name, frozenset(self._ids)))


def repr_records(self):
    return f"{self._name}{self._ids!r}"


def deepcopy_records(self, memo):
    return self

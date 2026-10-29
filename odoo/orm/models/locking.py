# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Locking: the existence of records and the row locks of the records."""

from __future__ import annotations

import re
import typing

import psycopg2.extensions

from odoo.exceptions import LockError
from odoo.tools import (
    partition, SQL,
)


from odoo.orm.core.identifiers import NewId
from odoo.orm.database.query import Query

if typing.TYPE_CHECKING:
    from typing import Self


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


def exists(self) -> Self:
    new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
    if not ids:
        return self
    query = Query(self)
    query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
    real_ids = (id_ for [id_] in self.env.execute_query(query.select()))
    valid_ids = {*real_ids, *new_ids}
    return self.browse(i for i in self._ids if i in valid_ids)


def lock_for_update(self, *, allow_referencing: bool=False) -> None:
    ids = {id_ for id_ in self._ids if id_}
    if not ids:
        return
    query = Query(self)
    query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
    # Use SKIP LOCKED instead of NOWAIT because the later aborts the
    # transaction and we do not want to use SAVEPOINTS.
    if allow_referencing:
        lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
    else:
        lock_sql = SQL("FOR UPDATE SKIP LOCKED")
    rows = self.env.execute_query(SQL("%s %s", query.select(), lock_sql))
    if len(rows) != len(ids):
        raise LockError(self.env._("Cannot grab a lock on records"))


def try_lock_for_update(self, *, allow_referencing: bool=False, limit: int | None=None) -> Self:
    new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
    if limit is not None:
        if len(new_ids) >= limit:
            return self.browse(new_ids[:limit])
        # keep the order of ids when trying to lock
        query = self.browse(ids)._as_query(ordered=True)
        query.limit = limit - len(new_ids)
    else:
        query = Query(self)
        query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
    if not ids:
        return self
    if allow_referencing:
        lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
    else:
        lock_sql = SQL("FOR UPDATE SKIP LOCKED")
    sql = SQL("%s %s", query.select(), lock_sql)
    real_ids = (id_ for [id_] in self.env.execute_query(sql))
    valid_ids = {*real_ids, *new_ids}
    return self.browse(i for i in self._ids if i in valid_ids)

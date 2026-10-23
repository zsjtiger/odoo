# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Read: the fields fetched for the records and the SQL that reads them."""

from __future__ import annotations

import re
import typing
from collections import deque

import psycopg2.extensions

from odoo.exceptions import MissingError
from odoo.tools import (
    OrderedSet,
    split_every,
    SQL,
)
from odoo.tools.constants import BIG_RECORDSET_SIZE


from odoo.orm.fields import Field

from odoo.orm.database.query import Query

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from typing import Self
    from odoo.orm.core.types import ValuesType


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


def read(self, fields: Sequence[str] | None=None, load: str='_classic_read') -> list[ValuesType]:
    if not fields:
        fields = list(self.fields_get(attributes=()))
    elif not self and not self.env.su:  # check field access, otherwise done during fetch()
        self._determine_fields_to_fetch(fields)
    self._origin.fetch(fields)
    return self._read_format(fnames=fields, load=load)


def fetch(self, field_names: Collection[str] | None=None) -> None:
    self = self._origin  # noqa: PLW0642 filtered out new records
    if not self or not (field_names is None or field_names):
        return

    fields_to_fetch = self._determine_fields_to_fetch(field_names, ignore_when_in_cache=True)
    queries = []
    # first determine a query that satisfies the domain and access rules
    if any(field.column_type for field in fields_to_fetch):
        for ids in split_every(BIG_RECORDSET_SIZE, self._ids):
            queries.append(self._search([('id', 'in', ids)], active_test=False))
    else:
        try:
            self.check_access('read')
        except MissingError:
            # Method fetch() should never raise a MissingError, but method
            # check_access() can, because it must read fields on self.
            # So we restrict 'self' to existing records (to avoid an extra
            # exists() at the end of the method).
            self = self.exists()
            self.check_access('read')
        if not fields_to_fetch:
            return
        # The query is split into domains of BIG_RECORDSET_SIZE so no one
        # query would have a domain large enough to spill to disk and slow
        # the transaction
        for ids in split_every(BIG_RECORDSET_SIZE, self._ids):
            queries.append(self.browse(ids)._as_query(ordered=False))

    # fetch the fields
    fetched = self.browse().union(
        self._fetch_query(query, fields_to_fetch)
        for query in queries
    )
    env = self.env
    if not env.su:
        env._add_to_access_cache(fetched)

    # force computation of fields
    for field_name in (field_names or ()):
        field = self._fields[field_name]
        if not field.store and any(field._cache_missing_ids(fetched)):
            fetched.mapped(field_name)

    # possibly raise exception for the records that could not be read
    if not env.su and fetched != self:
        forbidden = (self - fetched).exists()
        if not forbidden:
            return
        # Given that we have a cache of read permissions, the record may be
        # inaccessible from the query, however it was marked as accessible.
        # In such a case, read the fields in sudo.
        if forbidden.has_access('read'):
            self.sudo().fetch(field_names)
        else:
            # avoid cache pollution
            forbidden.invalidate_recordset([f.name for f in fields_to_fetch])
            domain = self._access_domain('read')
            raise forbidden._make_access_error_message('read', domain)  # noqa: EM101


def _fetch_field(self, field: Field) -> None:
    # determine which fields can be prefetched
    if field.prefetch and self.env.context.get('prefetch_fields', len(self) < BIG_RECORDSET_SIZE):
        fnames = [
            name
            for name, f in self._fields.items()
            # select fields with the same prefetch group
            if f.prefetch == field.prefetch
            # discard fields with groups that the user may not access
            if self.has_field_access(f, 'read')
        ]
        if field.name not in fnames:
            fnames.append(field.name)
    else:
        fnames = [field.name]
    self.fetch(fnames)


def _determine_fields_to_fetch(self, field_names: Collection[str] | None=None, ignore_when_in_cache: bool=False) -> list[Field]:
    if field_names is None:
        return [
            field
            for field in self._fields.values()
            if field.prefetch is True and self.has_field_access(field, 'read')
        ]

    if not field_names:
        return []

    fields_to_fetch: list[Field] = []
    fields_todo = deque[Field]()
    fields_done = {self._fields['id']}  # trick: ignore 'id'
    for field_name in field_names:
        try:
            field = self._fields[field_name]
        except KeyError as e:
            raise ValueError(f"Invalid field {field_name!r} on {self._name!r}") from e
        self.check_field_access(field, 'read')
        fields_todo.append(field)

    while fields_todo:
        field = fields_todo.popleft()
        if field in fields_done:
            continue
        fields_done.add(field)
        if ignore_when_in_cache and not any(field._cache_missing_ids(self)):
            # field is already in cache: don't fetch it
            continue
        if field.store:
            fields_to_fetch.append(field)
        else:
            # optimization: fetch field dependencies
            for dotname in self.pool.field_depends[field]:
                dep_field = self._fields[dotname.split('.', 1)[0]]
                if (
                    (not dep_field.store or dep_field.prefetch is True)
                    and self.has_field_access(dep_field, 'read')
                ):
                    fields_todo.append(dep_field)

    return fields_to_fetch


def _fetch_query(self, query: Query, fields: Sequence[Field]) -> Self:

    # determine columns fields and those with their own read() method
    column_fields: OrderedSet[Field] = OrderedSet()
    other_fields: OrderedSet[Field] = OrderedSet()
    for field in fields:
        if field.name == 'id':
            continue
        assert field.store or field.compute_sql
        (column_fields if field.column_type else other_fields).add(field)

    if column_fields:
        # the query may involve several tables: we need fully-qualified names
        sql_terms = [SQL.identifier(self._table, 'id')]
        for field in column_fields:
            sql = query.table[field.name]
            # flushing is necessary to retrieve the en_US value of fields without a translation
            # otherwise, re-create the SQL without flushing
            if not field.translate:
                to_flush = (f for f in sql._sql_tuple[2] if f != field)
                sql = SQL("%s", sql, to_flush=to_flush)
            sql_terms.append(sql)

        # select the given columns from the rows in the query
        rows = self.env.execute_query(query.select(*sql_terms))

        if not rows:
            return self.browse()

        # rows = [(id1, a1, b1), (id2, a2, b2), ...]
        # column_values = [(id1, id2, ...), (a1, a2, ...), (b1, b2, ...)]
        column_values = zip(*rows)
        ids = next(column_values)
        fetched = self.browse(ids)

        # If we assume that the value of a pending update is in cache, we
        # can avoid flushing pending updates if the fetched values do not
        # overwrite values in cache.
        for field, values in zip(column_fields, column_values, strict=True):
            # store values in cache, but without overwriting
            field._insert_cache(fetched, values)
    else:
        fetched = self.browse(query)

    # process non-column fields
    if fetched:
        for field in other_fields:
            field.read(fetched)

    return fetched

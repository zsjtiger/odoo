# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Write and create helpers: the values to write and the precomputed values of new records."""

from __future__ import annotations

import logging
import re
import typing
from collections import defaultdict

import psycopg2.errors
import psycopg2.extensions

from odoo.tools import (
    split_every, SQL,
)
from odoo.tools.translate import LazyTranslate


from odoo.orm.fields import Field, determine

from odoo.orm.core.utils import (
    SUPERUSER_ID,
)

if typing.TYPE_CHECKING:
    from odoo.orm.core.types import ValuesType


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

from odoo.orm.models import LOG_ACCESS_COLUMNS


def _prepare_create_values(self, vals_list: list[ValuesType]) -> list[ValuesType]:
    bad_names = ['id', 'parent_path']
    if self._log_access:
        # the superuser can set log_access fields while loading registry
        if not (self.env.uid == SUPERUSER_ID and not self.pool.ready):
            bad_names.extend(LOG_ACCESS_COLUMNS)

    # also discard precomputed readonly fields (to force their computation)
    bad_names.extend(
        fname
        for fname, field in self._fields.items()
        if field.precompute and field.readonly
    )

    result_vals_list = []
    for vals in vals_list:
        # add default values
        vals = self._add_missing_default_values(vals)

        # add magic fields
        for fname in bad_names:
            vals.pop(fname, None)
        if self._log_access:
            vals.setdefault('create_uid', self.env.uid)
            vals.setdefault('create_date', self.env.cr.now())
            vals.setdefault('write_uid', self.env.uid)
            vals.setdefault('write_date', self.env.cr.now())

        result_vals_list.append(vals)

    # add precomputed fields
    self._add_precomputed_values(result_vals_list)

    return result_vals_list


def _add_precomputed_values(self, vals_list: list[ValuesType]) -> None:
    precomputable = {
        fname: field
        for fname, field in self._fields.items()
        if field.precompute
    }
    if not precomputable:
        return

    # when several fields have the same compute, setting any of them should
    # not compute the others (and leave them to False)
    for vals in vals_list:
        given_fnames = [fname for fname in vals if fname in precomputable]
        for fname in given_fnames:
            for field in self.pool.field_computed[self._fields[fname]]:
                vals.setdefault(field.name, False)

    # determine which vals must be completed
    vals_list_todo = [
        vals
        for vals in vals_list
        if any(fname not in vals for fname in precomputable)
    ]
    if not vals_list_todo:
        return

    # create new records for the vals that must be completed
    records = self.browse().concat(self.new(vals) for vals in vals_list_todo)

    for record, vals in zip(records, vals_list_todo):
        vals['__precomputed__'] = precomputed = set()
        for fname, field in precomputable.items():
            if fname not in vals:
                # computed stored fields with a column
                # have to be computed before create
                # s.t. required and constraints can be applied on those fields.
                field_value = record.sudo()[fname] if field.compute_sudo else record[fname]
                vals[fname] = field.convert_to_write(field_value, self)
                precomputed.add(field)


def _compute_field_value(self, field: Field) -> None:
    determine(field.compute, self)

    if field.store and any(self._ids):
        # check constraints of the fields that have been computed
        fnames = [f.name for f in self.pool.field_computed[field]]
        self.filtered('id')._validate_fields(fnames)


def _write_multi(self, vals_list: list[ValuesType]) -> None:
    assert len(self) == len(vals_list)

    if not self:
        return
    self.env.transaction._wrote__ = True

    # determine records that require updating parent_path
    parent_records = self._parent_store_update_prepare(vals_list)

    if self._log_access:
        # set magic fields (already done by write(), but not for computed fields)
        log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
        vals_list = [(log_vals | vals) for vals in vals_list]

    # determine SQL updates, grouped by set of updated fields:
    # {(col1, col2, col3): [(id, val1, val2, val3)]}
    updates = defaultdict(list)
    for record, vals in zip(self, vals_list):
        # sort vals.items() by key, then retrieve its keys and values
        fnames, row = zip(*sorted(vals.items()))
        updates[fnames].append(record._ids + row)

    # perform updates (fnames, rows) in batches
    updates_list = [
        (fnames, sub_rows)
        for fnames, rows in updates.items()
        for sub_rows in split_every(UPDATE_BATCH_SIZE, rows)
    ]

    # update columns by group of updated fields
    for fnames, rows in updates_list:
        columns = []
        assignments = []
        for fname in fnames:
            field = self._fields[fname]
            assert field.store and field.column_type
            column = SQL.identifier(fname)
            # the type cast is necessary for some values, like NULLs
            expr = SQL('"__tmp".%s::%s', column, SQL.identifier(field.column_type[0]))
            if field.translate is True:
                # this is the SQL equivalent of:
                # None if expr is None else (
                #     (column or {'en_US': next(iter(expr.values()))}) | expr
                # )
                expr = SQL(
                    """CASE
                        WHEN (%(expr)s -> 0)::boolean THEN
                            COALESCE(
                                %(table)s.%(column)s,
                                jsonb_build_object('en_US', jsonb_path_query_first(%(expr)s -> 1, '$.*'))
                            ) || (%(expr)s -> 1)
                        ELSE (%(expr)s -> 1)
                    END""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                )
            if field.company_dependent:
                fallbacks = self.env['ir.default']._get_field_column_fallbacks(self._name, fname)
                expr = SQL(
                    """(SELECT jsonb_object_agg(d.key, d.value)
                    FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                    JOIN jsonb_each(%(fallbacks)s) f
                    ON d.key = f.key AND d.value != f.value)""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                    fallbacks=fallbacks
                )
            columns.append(column)
            assignments.append(SQL("%s = %s", column, expr))

        self.env.execute_query(SQL(
            """ UPDATE %(table)s
                SET %(assignments)s
                FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                WHERE %(table)s."id" = "__tmp"."id"
            """,
            table=SQL.identifier(self._table),
            assignments=SQL(", ").join(assignments),
            values=SQL(", ").join(rows),
            columns=SQL(", ").join(columns),
        ))

    # update parent_path
    if parent_records:
        parent_records._parent_store_update()

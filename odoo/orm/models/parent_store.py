# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Parent store: the tree of the records (parent_path) and the cycles of the hierarchy."""

from __future__ import annotations

import logging
import re
import typing
from collections import defaultdict

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import UserError
from odoo.tools import (
    SQL,
)
from odoo.tools.text.translate import _


if typing.TYPE_CHECKING:
    from typing import Self
    from odoo.orm.core.types import ValuesType


_logger = logging.getLogger('odoo.models')

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


def _parent_store_compute(self) -> None:
    if not self._parent_store:
        return

    # Each record is associated to a string 'parent_path', that represents
    # the path from the record's root node to the record. The path is made
    # of the node ids suffixed with a slash (see example below). The nodes
    # in the subtree of record are the ones where 'parent_path' starts with
    # the 'parent_path' of record.
    #
    #               a                 node | id | parent_path
    #              / \                  a  | 42 | 42/
    #            ...  b                 b  | 63 | 42/63/
    #                / \                c  | 84 | 42/63/84/
    #               c   d               d  | 85 | 42/63/85/
    #
    # Note: the final '/' is necessary to match subtrees correctly: '42/63'
    # is a prefix of '42/630', but '42/63/' is not a prefix of '42/630/'.
    _logger.info('Computing parent_path for table %s...', self._table)
    query = SQL(
        """ WITH RECURSIVE __parent_store_compute(id, parent_path) AS (
                SELECT row.id, concat(row.id, '/')
                FROM %(table)s row
                WHERE row.%(parent)s IS NULL
            UNION
                SELECT row.id, concat(comp.parent_path, row.id, '/')
                FROM %(table)s row, __parent_store_compute comp
                WHERE row.%(parent)s = comp.id
            )
            UPDATE %(table)s row SET parent_path = comp.parent_path
            FROM __parent_store_compute comp
            WHERE row.id = comp.id """,
        table=SQL.identifier(self._table),
        parent=SQL.identifier(self._parent_name),
    )
    self.env.cr.execute(query)
    self.invalidate_model(['parent_path'])


def _parent_store_create(self) -> None:
    if not self._parent_store:
        return

    updated = self.env.execute_query(SQL(
        """ UPDATE %(table)s node
            SET parent_path=concat((
                    SELECT parent.parent_path
                    FROM %(table)s parent
                    WHERE parent.id=node.%(parent)s
                ), node.id, '/')
            WHERE node.id IN %(ids)s
            RETURNING node.id, node.parent_path """,
        table=SQL.identifier(self._table),
        parent=SQL.identifier(self._parent_name),
        ids=tuple(self.ids),
    ))

    # update the cache of updated nodes, and determine what to recompute
    field = self._fields['parent_path']
    for id_, path in updated:
        field._update_cache(self.browse(id_), path)


def _parent_store_update_prepare(self, vals_list: list[ValuesType]) -> Self:
    if not self._parent_store:
        return self.browse()

    # associate each new parent_id to its corresponding record ids
    parent_to_ids = defaultdict(list)
    for id_, vals in zip(self._ids, vals_list):
        if self._parent_name in vals:
            parent_to_ids[vals[self._parent_name]].append(id_)

    if not parent_to_ids:
        return self.browse()

    self.flush_recordset([self._parent_name])

    # return the records for which the parent field will change
    sql_parent = SQL.identifier(self._parent_name)
    conditions = []
    for parent_id, ids in parent_to_ids.items():
        if parent_id:
            condition = SQL('(%s != %s OR %s IS NULL)', sql_parent, parent_id, sql_parent)
        else:
            condition = SQL('%s IS NOT NULL', sql_parent)
        conditions.append(SQL('("id" IN %s AND %s)', tuple(ids), condition))

    rows = self.env.execute_query(SQL(
        "SELECT id FROM %s WHERE %s ORDER BY id",
        SQL.identifier(self._table),
        SQL(" OR ").join(conditions),
    ))
    return self.browse(row[0] for row in rows)


def _parent_store_update(self) -> None:
    for parent, records in self.grouped(self._parent_name).items():
        # determine new prefix of parent_path of records
        prefix = parent.parent_path or ""

        # check for recursion
        if prefix:
            parent_ids = {int(label) for label in prefix.split('/')[:-1]}
            if not parent_ids.isdisjoint(records._ids):
                ir_model = self.env['ir.model']._get(self._name)
                raise UserError(_(
                    "You are creating a loop in your '%s' records. "
                    "A record cannot be a child of itself or one of its own sub-items. "
                    "Please select a different parent.",
                    ir_model.name,
                ))

        # update parent_path of all records and their descendants. The
        # descendants were matched with
        #     AND child.parent_path LIKE concat(node.parent_path, '%')
        # whose pattern comes from a column, so PostgreSQL gets no index
        # bounds and scans the table. The range below selects the same rows
        # from the index: parent_path ends with '/' and '0' is the next
        # character, so left(parent_path, -1) || '0' closes the range.
        updated = dict(self.env.execute_query(SQL(
            """ UPDATE %(table)s child
                SET parent_path = concat(%(prefix)s, substr(child.parent_path,
                        length(node.parent_path) - length(node.id || '/') + 1))
                FROM %(table)s node
                WHERE node.id IN %(ids)s
                AND child.parent_path >= node.parent_path
                AND child.parent_path < left(node.parent_path, -1) || '0'
                RETURNING child.id, child.parent_path """,
            table=SQL.identifier(self._table),
            prefix=prefix,
            ids=tuple(records.ids),
        )))

        # update the cache of updated nodes, and determine what to recompute
        field = self._fields['parent_path']
        for id_, path in updated.items():
            field._update_cache(self.browse(id_), path)
        records = self.browse(updated)
        records.modified(['parent_path'])


def _has_cycle(self, field_name=None) -> bool:
    if not field_name:
        field_name = self._parent_name

    field = self._fields.get(field_name)
    if not field:
        raise ValueError(f'Invalid field_name: {field_name!r}')

    if not (
        field.type in ('many2many', 'many2one')
        and field.comodel_name == self._name
        and field.store
    ):
        raise ValueError(f'Field must be a many2one or many2many relation on itself: {field_name!r}')

    if not self.ids or not self[field_name]:
        return False

    # must ignore 'active' flag, ir.rules, etc.
    # direct recursive SQL query with cycle detection for performance
    self.flush_model([field_name])
    if field.type == 'many2many':
        relation = field.relation
        column1 = field.column1
        column2 = field.column2
    else:
        relation = self._table
        column1 = 'id'
        column2 = field_name
    cr = self.env.cr
    cr.execute(SQL(
        """
        WITH RECURSIVE __reachability AS (
            SELECT %(col1)s AS source, %(col2)s AS destination
            FROM %(rel)s
            WHERE %(col1)s IN %(ids)s AND %(col2)s IS NOT NULL
        UNION
            SELECT r.source, t.%(col2)s
            FROM __reachability r
            JOIN %(rel)s t ON r.destination = t.%(col1)s AND t.%(col2)s IS NOT NULL
        )
        SELECT 1 FROM __reachability
        WHERE source = destination
        LIMIT 1
        """,
        ids=tuple(self.ids),
        rel=SQL.identifier(relation),
        col1=SQL.identifier(column1),
        col2=SQL.identifier(column2),
    ))
    return bool(cr.fetchone())

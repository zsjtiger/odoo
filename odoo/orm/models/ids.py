# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""External identifiers: the xmlids of the records."""

from __future__ import annotations

import io
import re
import typing
import uuid
from collections import defaultdict

import psycopg2.extensions

from odoo.tools import (
    SQL,
)


if typing.TYPE_CHECKING:
    from odoo.orm.core.types import DomainType, IdType


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


def _ensure_xml_id(self, skip=False):
    if skip:
        return ((record, None) for record in self)

    if not self:
        return iter([])

    if not self._is_an_ordinary_table():
        raise Exception(
            "You can not export the column ID of model %s, because the "
            "table %s is not an ordinary table."
            % (self._name, self._table))

    modname = '__export__'

    cr = self.env.cr
    cr.execute(SQL("""
        SELECT res_id, module, name
        FROM ir_model_data
        WHERE model = %s AND res_id IN %s
    """, self._name, tuple(self.ids)))
    xids = {
        res_id: (module, name)
        for res_id, module, name in cr.fetchall()
    }
    def to_xid(record_id):
        (module, name) = xids[record_id]
        return ('%s.%s' % (module, name)) if module else name

    # create missing xml ids
    missing = self.filtered(lambda r: r.id not in xids)
    if not missing:
        return (
            (record, to_xid(record.id))
            for record in self
        )

    xids.update(
        (r.id, (modname, '%s_%s_%s' % (
            r._table,
            r.id,
            uuid.uuid4().hex[:8],
        )))
        for r in missing
    )
    fields = ['module', 'model', 'name', 'res_id']

    # disable eventual async callback / support for the extent of
    # the COPY FROM, as these are apparently incompatible
    callback = psycopg2.extensions.get_wait_callback()
    psycopg2.extensions.set_wait_callback(None)
    try:
        cr.copy_from(io.StringIO(
            u'\n'.join(
                u"%s\t%s\t%s\t%d" % (
                    modname,
                    record._name,
                    xids[record.id][1],
                    record.id,
                )
                for record in missing
            )),
            table='ir_model_data',
            columns=fields,
        )
    finally:
        psycopg2.extensions.set_wait_callback(callback)
    self.env['ir.model.data'].invalidate_model(fields)

    return (
        (record, to_xid(record.id))
        for record in self
    )


def _get_external_ids(self) -> dict[IdType, list[str]]:
    result = defaultdict(list)
    domain: DomainType = [('model', '=', self._name), ('res_id', 'in', self.ids)]
    for data in self.env['ir.model.data'].sudo().search_read(domain, ['module', 'name', 'res_id'], order='id'):
        result[data['res_id']].append('%(module)s.%(name)s' % data)
    return {
        record.id: result[record._origin.id]
        for record in self
    }


def get_external_id(self) -> dict[IdType, str]:
    results = self._get_external_ids()
    return {key: val[0] if val else ''
            for key, val in results.items()}

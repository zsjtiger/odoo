# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Metadata: the fields description, the metadata of the records and the base url."""

from __future__ import annotations

import re
import typing
from collections import defaultdict

import psycopg2.errors
import psycopg2.extensions

from odoo.orm.models import BaseModel
from odoo.orm.models import LOG_ACCESS_COLUMNS


if typing.TYPE_CHECKING:
    from collections.abc import Collection
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


def fields_get(self, allfields: Collection[str] | None=None, attributes: Collection[str] | None=None) -> dict[str, ValuesType]:
    res = {}
    for fname, field in self._fields.items():
        if allfields and fname not in allfields:
            continue
        if not self.has_field_access(field, 'read'):
            continue

        description = field.get_description(self.env, attributes=attributes)
        if 'readonly' in description:
            description['readonly'] = description['readonly'] or not self.has_field_access(field, 'write')
        res[fname] = description

    return res


def get_metadata(self) -> list[ValuesType]:

    IrModelData = self.env['ir.model.data'].sudo()
    if self._log_access:
        res = self.read(LOG_ACCESS_COLUMNS)
    else:
        res = [{'id': x} for x in self.ids]


    xml_data = defaultdict(list)
    imds = IrModelData.search_read(
        [('model', '=', self._name), ('res_id', 'in', self.ids)],
        ['res_id', 'noupdate', 'module', 'name'],
        order='id DESC'
    )
    for imd in imds:
        xml_data[imd['res_id']].append({
            'xmlid': "%s.%s" % (imd['module'], imd['name']),
            'noupdate': imd['noupdate'],
        })

    for r in res:
        main = xml_data.get(r['id'], [{}])[-1]
        r['xmlid'] = main.get('xmlid', False)
        r['noupdate'] = main.get('noupdate', False)
        r['xmlids'] = xml_data.get(r['id'], [])[::-1]
    return res


def get_base_url(self) -> str:
    if len(self) > 1:
        raise ValueError("Expected singleton or no record: %s" % self)
    return self.env['ir.config_parameter'].sudo().get_str('web.base.url')


def _get_redirect_suggested_company(self) -> BaseModel | typing.Literal[False]:
    if 'company_id' in self:
        return self.company_id
    elif 'company_ids' in self:
        return (self.company_ids & self.env.user.company_ids)[:1]
    return False


def _can_return_content(self, field_name: str | None=None, access_token: str | None=None) -> bool:
    self.ensure_one()
    return False

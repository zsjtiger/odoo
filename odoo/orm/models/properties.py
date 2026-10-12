# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Properties: the definitions and the values of the properties fields."""

from __future__ import annotations

import logging
import re
import typing

import psycopg2.errors
import psycopg2.extensions

from odoo.tools import (
    SQL,
)
from odoo.tools.translate import LazyTranslate



from odoo.orm.core.utils import (
    parse_field_expr,
)

if typing.TYPE_CHECKING:
    pass


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



def get_property_definition(self, full_name: str) -> dict:
    self.browse().check_access("read")
    field_name, property_name = parse_field_expr(full_name)
    field = self._fields.get(field_name)
    if not field:
        raise ValueError(f"Invalid field {field_name!r} on model {self._name!r}")
    from odoo.orm.fields.properties import check_property_field_value_name  # noqa: PLC0415
    check_property_field_value_name(property_name)

    target_model = self.env[self._fields[field.definition_record].comodel_name]
    field_definition = target_model._fields[field.definition_record_field]
    result = self.env.execute_query_dict(SQL(
        """ SELECT definition
              FROM %(table)s, jsonb_array_elements(%(field)s) definition
             WHERE %(field)s IS NOT NULL AND definition->>'name' = %(name)s
             LIMIT 1 """,
        table=SQL.identifier(target_model._table),
        field=SQL.identifier(field.definition_record_field, to_flush=field_definition),
        name=property_name,
    ))
    return result[0]["definition"] if result else {}


def _clean_properties(self) -> None:
    for fname, field in self._fields.items():
        if field.type != 'properties':
            continue
        for record in self:
            old_value = record[fname]._values
            if not old_value:
                continue

            definitions = field._get_properties_definition(record)
            all_names = {definition['name'] for definition in definitions}
            new_values = {name: value for name, value in old_value.items() if name in all_names}
            if len(new_values) != len(old_value):
                record[fname] = new_values


def _additional_allowed_keys_properties_definition(self):
    return ()


def _convert_to_cache_properties_definition(self, value):
    return value


def _convert_to_column_properties_definition(self, value):
    return value

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Onchange: the methods to apply when the values of a form change."""

from __future__ import annotations

import logging
import re
import typing

import psycopg2.errors
import psycopg2.extensions

from odoo.tools.translate import _, LazyTranslate


from odoo.orm.fields import Field


if typing.TYPE_CHECKING:
    from collections.abc import Collection


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



def _has_onchange(self, field: Field, other_fields: Collection[Field]) -> bool:
    return (field.name in self._onchange_methods) or any(
        dep in other_fields
        for dep in self.pool.get_dependent_fields(field.base_field)
    )


def _apply_onchange_methods(self, field_name: str, result: dict, excluded_methods=()) -> None:
    for method in self._onchange_methods.get(field_name, ()):
        if method in excluded_methods:
            continue
        res = method(self)
        if not res:
            continue
        if res.get('value'):
            for key, val in res['value'].items():
                if key in self._fields and key != 'id':
                    self[key] = val
        if res.get('warning'):
            result['warnings'].add((
                res['warning'].get('title') or _("Warning"),
                res['warning'].get('message') or "",
                res['warning'].get('type') or "",
            ))

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Copy: the duplication of records."""

from __future__ import annotations

import re
import typing
from collections import defaultdict

import psycopg2.errors
import psycopg2.extensions



from odoo.orm.core.commands import Command
from odoo.orm.models import MAGIC_COLUMNS


if typing.TYPE_CHECKING:
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


def copy_data(self, default: ValuesType | None=None) -> list[ValuesType]:
    vals_list = []
    default = dict(default or {})
    # avoid recursion through already copied records in case of circular relationship
    if '__copy_data_seen' not in self.env.context:
        self = self.with_context(__copy_data_seen=defaultdict(set))

    # build a black list of fields that should not be copied
    blacklist = {*MAGIC_COLUMNS, 'parent_path'}
    whitelist = {name for name, field in self._fields.items() if not field.inherited}

    blacklist_stack = [self]
    while blacklist_stack:
        for parent_model, parent_field in blacklist_stack.pop()._inherits.items():
            blacklist.add(parent_field)
            if parent_field in default:
                # all the fields of 'parent_model' are given by the record:
                # default[parent_field], except the ones redefined in self
                blacklist.update(set(self.env[parent_model]._fields) - whitelist)
            else:
                blacklist_stack.append(self.env[parent_model])

    fields_to_copy = {name: field
                      for name, field in self._fields.items()
                      if field.copy and name not in default and name not in blacklist}
    active_langs = self.env['res.lang']._get_active_by('code')

    for record in self:
        seen_map = self.env.context['__copy_data_seen']
        if record.id in seen_map[record._name]:
            vals_list.append(None)
            continue
        seen_map[record._name].add(record.id)

        vals = default.copy()

        for name, field in fields_to_copy.items():
            if callable(field.copy):
                vals[name] = field.copy(record)
            elif field.type == 'one2many':
                # duplicate following the order of the ids for deterministic pairing
                lines = record[name].sorted(key='id').copy_data()
                # the lines are duplicated using the wrong (old) parent, but then are
                # reassigned to the correct one thanks to the (Command.CREATE, 0, ...)
                vals[name] = [Command.create(line) for line in lines if line]
            elif field.type == 'many2many':
                # copy only links that we can read, otherwise the write will fail
                vals[name] = [Command.set(record[name]._filtered_access('read').ids)]
            elif field.translate:
                translations = record._get_stored_translations(name)
                if not translations:
                    vals[name] = False
                elif field.translate is True:
                    vals[name] = translations.normalize(record.env, field)
                else:
                    vals[name] = translations.translated(
                        record.env, field, 'en_US', {lang: {} for lang in active_langs}
                    )
            else:
                vals[name] = field.convert_to_write(record[name], record)

        vals_list.append(vals)

    return vals_list


def copy(self, default: ValuesType | None=None) -> Self:
    vals_list = self.with_context(active_test=False).copy_data(default)
    return self.create(vals_list)

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Model hooks: the SQL table, the constraints, the ondelete and the onchange methods of the model."""

from __future__ import annotations

import functools
import logging
import re
import typing
from collections import defaultdict
from inspect import getmembers

import psycopg2.extensions

from odoo.tools import (
    SQL,
)


from odoo.orm.core import decorators as api
from odoo.orm.fields import Field


if typing.TYPE_CHECKING:
    pass


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


def _table_sql(self) -> SQL:
    table_sql = SQL.identifier(self._table)
    if not self._depends:
        return table_sql

    # add self._depends (and its transitive closure) as metadata to table_sql
    fields_to_flush: list[Field] = []
    models = [self]
    while models:
        current_model = models.pop()
        for model_name, field_names in current_model._depends.items():
            model = self.env[model_name]
            models.append(model)
            fields_to_flush.extend(model._fields[fname] for fname in field_names)

    return SQL("%s", table_sql, to_flush=fields_to_flush)


def _constraint_methods(self):
    def is_constraint(func):
        return callable(func) and hasattr(func, '_constrains')

    def wrap(func, names):
        # wrap func into a proxy function with explicit '_constrains'
        @api.constrains(*names)
        def wrapper(self):
            return func(self)
        return wrapper

    cls = self.env.registry[self._name]
    methods = []
    for attr, func in getmembers(cls, is_constraint):
        if callable(func._constrains):
            func = wrap(func, func._constrains(self.sudo()))
        for name in func._constrains:
            field = cls._fields.get(name)
            if not field:
                _logger.warning("method %s.%s: @constrains parameter %r is not a field name", cls._name, attr, name)
            elif not (field.store or field.inverse or field.inherited):
                _logger.warning("method %s.%s: @constrains parameter %r is not writeable", cls._name, attr, name)
        methods.append(func)

    # optimization: memoize result on cls, it will not be recomputed
    cls._constraint_methods = methods
    return methods


def _ondelete_methods(self):
    def is_ondelete(func):
        return callable(func) and hasattr(func, '_ondelete')

    cls = self.env.registry[self._name]
    methods = [func for _, func in getmembers(cls, is_ondelete)]
    # optimization: memoize results on cls, it will not be recomputed
    cls._ondelete_methods = methods
    return methods


def _onchange_methods(self):
    def is_onchange(func):
        return callable(func) and hasattr(func, '_onchange')

    # collect onchange methods on the model's class
    cls = self.env.registry[self._name]
    methods = defaultdict(list)
    for _attr, func in getmembers(cls, is_onchange):
        missing = []
        for name in func._onchange:
            if name not in cls._fields:
                missing.append(name)
            methods[name].append(func)
        if missing:
            _logger.warning(
                "@api.onchange%r parameters must be field names -> not valid: %s",
                func._onchange, missing
            )

    # add onchange methods to implement "change_default" on fields
    def onchange_default(field, self):
        value = field.convert_to_write(self[field.name], self)
        condition = "%s=%s" % (field.name, value)
        defaults = self.env['ir.default']._get_model_defaults(self._name, condition)
        self.update(defaults)

    for name, field in cls._fields.items():
        if field.change_default:
            methods[name].append(functools.partial(onchange_default, field))

    # optimization: memoize result on cls, it will not be recomputed
    cls._onchange_methods = methods
    return methods

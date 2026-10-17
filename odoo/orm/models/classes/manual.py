"""The manual models and fields: the models and the fields created in the database rather than in the code."""

from __future__ import annotations

import logging
import typing
from odoo.orm import models
from odoo.orm import fields  # must be imported after models
from odoo.tools import (
    OrderedSet,
    sql,
)

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.models import BaseModel

from .fields import add_field
from .registration import add_to_registry

_logger = logging.getLogger('odoo.registry')


def _add_manual_models(env: Environment):
    """ Add extra models to the registry. """
    # clean up registry first
    removed_fields = OrderedSet()
    for name, model_cls in list(env.registry.items()):
        if model_cls._custom:
            removed_fields.update(model_cls._fields.values())
            del env.registry.models[name]
            # remove the model's name from its parents' _inherit_children
            for parent_cls in model_cls.__bases__:
                if hasattr(parent_cls, 'pool'):
                    parent_cls._inherit_children.discard(name)

    if removed_fields:
        env.registry._discard_fields(list(removed_fields))

    # we cannot use self._fields to determine translated fields, as it has not been set up yet
    env.cr.execute("SELECT *, name->>'en_US' AS name FROM ir_model WHERE state = 'manual'")
    for model_data in env.cr.dictfetchall():
        attrs = env['ir.model']._instanciate_attrs(model_data)

        # adapt _auto and _log_access if necessary
        table_name = model_data["model"].replace(".", "_")
        table_kind = sql.table_kind(env.cr, table_name)
        if table_kind not in (sql.TableKind.Regular, None):
            _logger.info(
                "Model %r is backed by table %r which is not a regular table (%r), disabling automatic schema management",
                model_data["model"], table_name, table_kind,
            )
            attrs['_auto'] = False
            env.cr.execute(
                """ SELECT a.attname
                    FROM pg_attribute a
                    JOIN pg_class t ON a.attrelid = t.oid AND t.relname = %s
                    WHERE a.attnum > 0 -- skip system columns
                    AND t.relnamespace = current_schema::regnamespace """,
                [table_name]
            )
            columns = {colinfo[0] for colinfo in env.cr.fetchall()}
            attrs['_log_access'] = set(models.LOG_ACCESS_COLUMNS) <= columns

        model_def = type('CustomDefinitionModel', (models.Model,), attrs)
        add_to_registry(env.registry, model_def)


def _add_manual_fields(model_cls: type[BaseModel], env: Environment):
    """ Add extra fields on model. """
    IrModelFields = env['ir.model.fields']

    fields_data = IrModelFields._get_manual_field_data(model_cls._name)
    for name, field_data in fields_data.items():
        if name not in model_cls._fields and field_data['state'] == 'manual':
            try:
                attrs = IrModelFields._instanciate_attrs(field_data)
                if attrs:
                    field = fields.Field._by_type__[field_data['ttype']](**attrs)
                    add_field(model_cls, name, field)
            except Exception:
                _logger.exception("Failed to load field %s.%s: skipped", model_cls._name, field_data['name'])

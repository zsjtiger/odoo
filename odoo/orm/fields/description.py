"""Description of the fields, as returned by fields_get: the attributes exposed to the clients."""

from __future__ import annotations

import typing
from odoo.exceptions import AccessError
from odoo.tools import SQL
from odoo.orm.database.query import Query

if typing.TYPE_CHECKING:
    from collections.abc import Collection
    from odoo.orm.models.environments import Environment
    from odoo.orm.core.types import ValuesType


def get_description(self, env: Environment, attributes: Collection[str] | None = None) -> ValuesType:
    """ Return a dictionary that describes the field ``self``. """
    desc = {}
    for attr, prop in self.description_attrs:
        if attributes is not None and attr not in attributes:
            continue
        if not prop.startswith('_description_'):
            continue
        value = getattr(self, prop)
        if callable(value):
            value = value(env)
        if value is not None:
            desc[attr] = value

    return desc


def _description_depends(self, env: Environment):
    return env.registry.field_depends[self]


def _description_searchable(self) -> bool:
    return bool(self.store or self.search or self.compute_sql)


def _description_sortable(self, env: Environment):
    if self.column_type and (self.store or self.compute_sql):  # shortcut
        return True
    if self.inherited_field and self.inherited_field._description_sortable(env):
        # avoid compuation for inherited field
        return True

    model = env[self.model_name]
    if self.relational and getattr(env[self.comodel_name], '_access_domain_heavy', False):
        return False
    query = model._as_query(ordered=False)
    try:
        model._order_field_to_sql(query.table, self.name, SQL(), SQL())
        return True
    except (ValueError, AccessError):
        return False


def _description_groupable(self, env: Environment):
    if self.column_type and (self.store or self.compute_sql):  # shortcut
        return True
    if self.inherited_field and self.inherited_field._description_groupable(env):
        # avoid compuation for inherited field
        return True
    from odoo.orm.models import BaseModel  # noqa: PLC0415
    if self.type != 'many2many' and env.registry[self.model_name]._read_group_groupby is BaseModel._read_group_groupby:
        # the default implementation has an edge case for many2many
        return False

    model = env[self.model_name]
    if self.relational and getattr(env[self.comodel_name], '_access_domain_heavy', False):
        return False
    groupby = self.name if self.type not in ('date', 'datetime') else f"{self.name}:month"
    try:
        model._read_group_groupby(Query(model).table, groupby)
        return True
    except (ValueError, AccessError):
        return False


def _description_aggregator(self, env: Environment):
    if not self.aggregator or (self.column_type and (self.store or self.compute_sql)):  # shortcut
        return self.aggregator
    if self.inherited_field and self.inherited_field._description_aggregator(env):
        # avoid compuation for inherited field
        return self.inherited_field.aggregator
    from odoo.orm.models import BaseModel  # noqa: PLC0415
    if env.registry[self.model_name]._read_group_select is BaseModel._read_group_select:
        # the default implementation does not handle additional fields
        return False

    model = env[self.model_name]
    if self.relational and getattr(env[self.comodel_name], '_access_domain_heavy', False):
        return None
    query = model._as_query(ordered=False)
    try:
        model._read_group_select(query.table, f"{self.name}:{self.aggregator}")
        return self.aggregator
    except (ValueError, AccessError):
        return None


def _description_string(self, env: Environment) -> str:
    if self.string and env.lang:
        model_name = self.base_field.model_name
        field_string = env['ir.model.fields'].get_field_string(model_name)
        return field_string.get(self.name) or self.string
    return self.string


def _description_help(self, env: Environment):
    if self.help and env.lang:
        model_name = self.base_field.model_name
        field_help = env['ir.model.fields'].get_field_help(model_name)
        return field_help.get(self.name) or self.help
    return self.help


def _description_falsy_value_label(self, env) -> str | None:
    return env._(self.falsy_value_label) if self.falsy_value_label else None # pylint: disable=gettext-variable


def _description_group_expand(self, env) -> bool:
    return bool(self.group_expand)


def is_editable(self) -> bool:
    """ Return whether the field can be editable in a view. """
    return not self.readonly

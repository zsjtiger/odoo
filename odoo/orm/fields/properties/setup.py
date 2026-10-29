"""Setup of the properties fields, and their writes and computation."""

from __future__ import annotations

import copy
import json
import typing
from odoo.exceptions import UserError
from odoo.orm.fields import _logger

if typing.TYPE_CHECKING:
    pass

from .base import Properties
from .mapping import Property

def _setup_attrs__(self, model_class, name):
    super(Properties, self)._setup_attrs__(model_class, name)
    self._setup_definition_attrs(model_class)


def _setup_definition_attrs(self, model_class):
    if self.definition:
        # determine definition_record and definition_record_field
        assert self.definition.count(".") == 1
        self.definition_record, self.definition_record_field = self.definition.rsplit('.', 1)

        if not self.related:
            # make the field computed, and set its dependencies
            self._depends = (self.definition_record, )
            self.compute = self._compute


def setup(self, model):
    if not self._setup_done and self.definition_record and self.definition_record_field:
        definition_record_model = model.env[model._fields[self.definition_record].comodel_name]
        definition_record_field = definition_record_model._fields[self.definition_record_field]
        definition_record_field.setup(definition_record_model)
        definition_record_field.properties_fields += (self,)
    return super(Properties, self).setup(model)


def setup_related(self, model):
    super(Properties, self).setup_related(model)
    if self.inherited_field and not self.definition:
        self.definition = self.inherited_field.definition
        self._setup_definition_attrs(model)


def write(self, records, value):
    """Check if the properties definition has been changed.

    To avoid extra SQL queries used to detect definition change, we add a
    flag in the properties list. Parent update is done only when this flag
    is present, delegating the check to the caller (generally web client).

    For deletion, we need to keep the removed property definition in the
    list to be able to put the delete flag in it. Otherwise we have no way
    to know that a property has been removed.
    """
    if isinstance(value, str):
        value = json.loads(value)

    if isinstance(value, Property):
        value = value._values

    if len(records[self.definition_record]) > 1 and value:
        raise UserError(records.env._("Updating records with different property fields definitions is not supported. Update by separate definition instead."))

    if isinstance(value, dict):
        # don't need to write on the container definition
        return super(Properties, self).write(records, value)

    definition_changed = any(
        definition.get('definition_changed')
        or definition.get('definition_deleted')
        for definition in (value or [])
    )
    if definition_changed:
        value = [
            definition for definition in value
            if not definition.get('definition_deleted')
        ]
        for definition in value:
            definition.pop('definition_changed', None)

        # update the properties definition on the container
        container = records[self.definition_record]
        if container:
            properties_definition = copy.deepcopy(value)
            for property_definition in properties_definition:
                property_definition.pop('value', None)
            container[self.definition_record_field] = properties_definition

            _logger.info('Properties field: User #%i changed definition of %r', records.env.user.id, container)

    return super(Properties, self).write(records, value)


def _compute(self, records):
    """Add the default properties value when the container is changed."""
    for record in records.sudo():
        record[self.name] = self._add_default_values(
            record.env,
            {self.name: record[self.name], self.definition_record: record[self.definition_record]},
        )


def _get_properties_definition(self, record):
    """Return the properties definition of the given record."""
    container = record[self.definition_record]
    if container:
        return container.sudo()[self.definition_record_field]

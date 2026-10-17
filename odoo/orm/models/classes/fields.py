"""The addition and the removal of the fields of the model classes."""

from __future__ import annotations

import logging
import typing
from odoo.orm import fields  # must be imported after models
from odoo.exceptions import ValidationError

if typing.TYPE_CHECKING:
    from odoo.fields import Field
    from odoo.models import BaseModel

from .base import discardattr

_logger = logging.getLogger('odoo.registry')


def add_field(model_cls: type[BaseModel], name: str, field: Field, shareable: bool = False):
    """Add ``field`` to ``model_cls`` under ``name`` and set its _shareable flag."""
    # Assert the name is an existing field in the model, or any model in the _inherits
    # or a custom field (starting by `x_`)
    is_class_field = any(
        isinstance(getattr(model, name, None), fields.Field)
        for model in [model_cls] + [model_cls.pool[inherit] for inherit in model_cls._inherits]
    )
    if not (is_class_field or model_cls.pool['ir.model.fields']._is_manual_name(None, name)):
        raise ValidationError(  # pylint: disable=missing-gettext
            f"The field `{name}` is not defined in the `{model_cls._name}` Python class and does not start with 'x_'"
        )

    # Assert the attribute to assign is a Field
    if not isinstance(field, fields.Field):
        raise ValidationError("You can only add `fields.Field` objects to a model fields")  # pylint: disable=missing-gettext

    if not isinstance(getattr(model_cls, name, field), fields.Field):
        _logger.warning("In model %r, field %r overriding existing value", model_cls._name, name)
    setattr(model_cls, name, field)
    if field._shareable != shareable:
        field._shareable = shareable
    field.__set_name__(model_cls, name)
    # add field as an attribute and in model_cls._fields__ (for reflection)
    model_cls._fields__[name] = field


def pop_field(model_cls: type[BaseModel], name: str) -> Field | None:
    """ Remove the field with the given ``name`` from the model class of ``model``. """
    field = model_cls._fields__.pop(name, None)
    discardattr(model_cls, name)
    if model_cls._rec_name == name:
        # fixup _rec_name and display_name's dependencies
        model_cls._rec_name = None
        if model_cls.display_name in model_cls.pool.field_depends:
            model_cls.pool.field_depends[model_cls.display_name] = tuple(
                dep for dep in model_cls.pool.field_depends[model_cls.display_name] if dep != name
            )
    return field

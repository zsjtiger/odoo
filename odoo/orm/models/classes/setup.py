"""The setup of the model classes: their fields, their inherited fields and the setup of the models of the registry."""

from __future__ import annotations

import logging
import typing
from collections import defaultdict
from odoo.orm import models
from odoo.tools import (
    frozendict,
    sql,
)
from odoo.tools.text.translate import FIELD_TRANSLATE

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.models import BaseModel

from .base import SHARED_FIELD_CACHE, discardattr
from .fields import add_field, pop_field
from .manual import _add_manual_fields, _add_manual_models

_logger = logging.getLogger('odoo.registry')


def setup_model_classes(env: Environment):
    registry = env.registry

    # we must setup ir.model before adding manual fields because _add_manual_models may
    # depend on behavior that is implemented through overrides, such as is_mail_thread which
    # is implemented through an override to env['ir.model']._instanciate_attrs
    _prepare_setup(registry['ir.model'])

    # add manual models
    if registry._init_modules:
        _add_manual_models(env)

    # prepare the setup on all models
    models_classes = list(registry.values())
    for model_cls in models_classes:
        _prepare_setup(model_cls)

    # do the actual setup
    for model_cls in models_classes:
        _setup(model_cls, env)

    for model_cls in models_classes:
        _setup_fields(model_cls, env)

    for model_cls in models_classes:
        model_cls._fields_update_order__ = {
            field: (field.write_sequence, i)
            for i, field in enumerate(model_cls._fields.values())
        }
        model_cls(env, (), ())._post_model_setup__()


def _prepare_setup(model_cls: type[BaseModel]):
    """ Prepare the setup of the model. """
    if model_cls._setup_done__:
        assert model_cls.__bases__ == model_cls._base_classes__
        return

    # changing base classes is costly, do it only when necessary
    if model_cls.__bases__ != model_cls._base_classes__:
        model_cls.__bases__ = model_cls._base_classes__

    # reset those attributes on the model's class for _setup_fields() below
    for attr in ('_rec_name', '_active_name'):
        discardattr(model_cls, attr)

    # reset properties memoized on model_cls
    model_cls._constraint_methods = models.BaseModel._constraint_methods
    model_cls._ondelete_methods = models.BaseModel._ondelete_methods
    model_cls._onchange_methods = models.BaseModel._onchange_methods


def _setup(model_cls: type[BaseModel], env: Environment):
    """ Determine all the fields of the model. """
    if model_cls._setup_done__:
        return

    # the classes that define this model, i.e., the ones that are not
    # registry classes; the purpose of this attribute is to behave as a
    # cache of [c for c in model_cls.mro() if not is_model_class(c))], which
    # is heavily used in function fields.resolve_mro()
    model_cls._model_classes__ = tuple(c for c in model_cls.mro() if getattr(c, 'pool', None) is None)

    # 1. determine the proper fields of the model: the fields defined on the
    # class and magic fields, not the inherited or custom ones

    # retrieve fields from parent classes, and duplicate them on model_cls to
    # avoid clashes with inheritance between different models
    for name in model_cls._fields:
        discardattr(model_cls, name)
    model_cls._fields__.clear()

    # collect the definitions of each field (base definition + overrides)
    definitions = defaultdict(list)
    for cls in reversed(model_cls._model_classes__):
        # this condition is an optimization of is_model_definition(cls)
        if isinstance(cls, models.MetaModel):
            for field in cls._field_definitions:
                definitions[field.name].append(field)

    for name, fields_ in definitions.items():
        if f'{model_cls._name}.{name}' in model_cls.pool._database_translated_fields:
            # the field is currently translated in the database; ensure the
            # field is translated to avoid converting its column to varchar
            # and losing data
            translate = next((
                field._args__['translate'] for field in reversed(fields_) if 'translate' in field._args__
            ), False)
            if not translate:
                field_translate = FIELD_TRANSLATE.get(
                    model_cls.pool._database_translated_fields[f'{model_cls._name}.{name}'],
                    True
                )
                # patch the field definition by adding an override
                _logger.debug("Patching %s.%s with translate=True", model_cls._name, name)
                fields_.append(type(fields_[0])(translate=field_translate))
        if f'{model_cls._name}.{name}' in model_cls.pool._database_company_dependent_fields:
            # the field is currently company dependent in the database; ensure
            # the field is company dependent to avoid converting its column to
            # the base data type
            company_dependent = next((
                field._args__['company_dependent'] for field in reversed(fields_) if 'company_dependent' in field._args__
            ), False)
            if not company_dependent:
                # validate column type again in case the column type is changed by upgrade script
                rows = env.execute_query(sql.SQL(
                    'SELECT data_type FROM information_schema.columns'
                    ' WHERE table_name = %s AND column_name = %s AND table_schema = current_schema',
                    model_cls._table, name,
                ))
                if rows and rows[0][0] == 'jsonb':
                    # patch the field definition by adding an override
                    _logger.debug("Patching %s.%s with company_dependent=True", model_cls._name, name)
                    fields_.append(type(fields_[0])(company_dependent=True))
        if all(field._shareable for field in fields_):
            if len(fields_) == 1 and fields_[0].model_name == model_cls._name:
                model_cls._fields__[name] = fields_[0]
            else:
                cache_key = (model_cls._name, tuple(fields_))
                if (field_ := SHARED_FIELD_CACHE.get(cache_key)) is None:
                    Field = type(fields_[-1])
                    field_ = Field(_base_fields__=tuple(fields_))
                    SHARED_FIELD_CACHE[cache_key] = field_
                add_field(model_cls, name, field_, shareable=True)
        else:
            Field = type(fields_[-1])
            add_field(model_cls, name, Field(_base_fields__=tuple(fields_)))

    # 2. add manual fields
    if model_cls.pool._init_modules:
        _add_manual_fields(model_cls, env)

    # 3. make sure that parent models determine their own fields, then add
    # inherited fields to model_cls
    _check_inherits(model_cls)
    for parent_name in model_cls._inherits:
        _setup(model_cls.pool[parent_name], env)
    _add_inherited_fields(model_cls)

    # 4. initialize more field metadata
    model_cls._setup_done__ = True

    for field in model_cls._fields.values():
        field.prepare_setup()

    # 5. determine and validate rec_name
    if model_cls._rec_name:
        assert model_cls._rec_name in model_cls._fields, \
            "Invalid _rec_name=%r for model %r" % (model_cls._rec_name, model_cls._name)
    elif 'name' in model_cls._fields:
        model_cls._rec_name = 'name'
    elif model_cls._custom and 'x_name' in model_cls._fields:
        model_cls._rec_name = 'x_name'

    # 6. determine and validate active_name
    if model_cls._active_name:
        assert (model_cls._active_name in model_cls._fields
                and model_cls._active_name in ('active', 'x_active')), \
            ("Invalid _active_name=%r for model %r; only 'active' and "
            "'x_active' are supported and the field must be present on "
            "the model") % (model_cls._active_name, model_cls._name)
    elif 'active' in model_cls._fields:
        model_cls._active_name = 'active'
    elif 'x_active' in model_cls._fields:
        model_cls._active_name = 'x_active'

    # 7. determine table objects
    assert not model_cls._table_object_definitions, "model_cls is a registry model"
    model_cls._table_objects = frozendict({
        cons.full_name(model_cls): cons
        for cls in reversed(model_cls._model_classes__)
        if isinstance(cls, models.MetaModel)
        for cons in cls._table_object_definitions
    })


def _check_inherits(model_cls: type[BaseModel]):
    for comodel_name, field_name in model_cls._inherits.items():
        field = model_cls._fields.get(field_name)
        if not field or field.type != 'many2one':
            raise TypeError(
                f"Missing many2one field definition for _inherits reference {field_name!r} in model {model_cls._name!r}. "
                f"Add a field like: {field_name} = fields.Many2one({comodel_name!r}, required=True, ondelete='cascade')"
            )
        if not (field.delegate and field.required and (field.ondelete or "").lower() in ("cascade", "restrict")):
            raise TypeError(
                f"Field definition for _inherits reference {field_name!r} in {model_cls._name!r} "
                "must be marked as 'delegate', 'required' with ondelete='cascade' or 'restrict'"
            )


def _add_inherited_fields(model_cls: type[BaseModel]):
    """ Determine inherited fields. """
    if model_cls._abstract or not model_cls._inherits:
        return

    # determine which fields can be inherited
    to_inherit = {
        name: (parent_fname, field)
        for parent_model_name, parent_fname in model_cls._inherits.items()
        for name, field in model_cls.pool[parent_model_name]._fields.items()
    }

    # add inherited fields that are not redefined locally
    for name, (parent_fname, field) in to_inherit.items():
        if name not in model_cls._fields:
            # inherited fields are implemented as related fields, with the
            # following specific properties:
            #  - reading inherited fields should not bypass access rights
            #  - copy inherited fields iff their original field is copied
            field_cls = type(field)
            add_field(model_cls, name, field_cls(
                inherited=True,
                inherited_field=field,
                related=f"{parent_fname}.{name}",
                related_sudo=False,
                copy=field.copy,
                readonly=field.readonly,
                export_string_translation=field.export_string_translation,
            ))


def _setup_fields(model_cls: type[BaseModel], env: Environment):
    """ Setup the fields, except for recomputation triggers. """
    bad_fields = []
    many2one_company_dependents = model_cls.pool.many2one_company_dependents
    model = model_cls(env, (), ())
    for name, field in model_cls._fields.items():
        try:
            field.setup(model)
        except Exception:
            if field.base_field.manual:
                # Something goes wrong when setup a manual field.
                # This can happen with related fields using another manual many2one field
                # that hasn't been loaded because the comodel does not exist yet.
                # This can also be a manual function field depending on not loaded fields yet.
                bad_fields.append(name)
                continue
            raise
        if field.type == 'many2one' and field.company_dependent:
            many2one_company_dependents.add(field.comodel_name, field)

    for name in bad_fields:
        pop_field(model_cls, name)

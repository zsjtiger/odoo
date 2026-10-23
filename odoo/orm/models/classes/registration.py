"""The registration of the model definitions in the registry: the checks of the extensions, and the attributes of the new model classes."""

from __future__ import annotations

import logging
import typing
from types import MappingProxyType
from odoo.orm.core.utils import check_pg_name
from odoo.tools import (
    OrderedSet,
    LastOrderedSet,
    frozendict,
)
from odoo.tools.safe_eval import safe_checker

if typing.TYPE_CHECKING:
    from odoo.models import BaseModel
    from odoo.modules.registry import Registry

from .base import is_model_class, is_model_definition

_logger = logging.getLogger('odoo.registry')


def add_to_registry(registry: Registry, model_def: type[BaseModel]) -> type[BaseModel]:
    """ Add a model definition to the given registry, and return its
    corresponding model class.  This function creates or extends a model class
    for the given model definition.
    """
    assert is_model_definition(model_def)

    if hasattr(model_def, '_constraints'):
        _logger.warning("Model attribute '_constraints' is no longer supported, "
                        "please use @api.constrains on methods instead.")
    if hasattr(model_def, '_sql_constraints'):
        _logger.warning("Model attribute '_sql_constraints' is no longer supported, "
                        "please define models.Constraint on the model.")

    # all models except 'base' implicitly inherit from 'base'
    name = model_def._name
    parent_names = list(model_def._inherit)
    if name != 'base':
        parent_names.append('base')

    # create or retrieve the model's class
    if name in parent_names:
        if name not in registry:
            raise TypeError(f"Model {name!r} does not exist in registry.")
        model_cls = registry[name]
        _check_model_extension(model_cls, model_def)
    else:
        model_cls = type(name, (model_def,), {
            'pool': registry,                       # this makes it a model class
            '_name': name,
            '_register': False,
            '_original_module': model_def._module,
            '_inherit_module': {},                  # map parent to introducing module
            '_inherit_children': OrderedSet(),      # names of children models
            '_inherits_children': set(),            # names of children models
            '_fields__': {},                        # populated in _setup()
            '_fields_update_order__': {},           # populated in _post_model_setup__()
            '_table_objects': frozendict(),         # populated in _setup()
        })
        model_cls._fields = MappingProxyType(model_cls._fields__)

    # determine all the classes the model should inherit from
    bases = LastOrderedSet([model_def])
    for parent_name in parent_names:
        if parent_name not in registry:
            raise TypeError(f"Model {name!r} inherits from non-existing model {parent_name!r}.")
        parent_cls = registry[parent_name]
        if parent_name == name:
            for base in parent_cls._base_classes__:
                bases.add(base)
        else:
            _check_model_parent_extension(model_cls, model_def, parent_cls)
            bases.add(parent_cls)
            model_cls._inherit_module[parent_name] = model_def._module
            parent_cls._inherit_children.add(name)

    # model_cls.__bases__ must be assigned those classes; however, this
    # operation is quite slow, so we do it once in method _prepare_setup()
    model_cls._base_classes__ = tuple(bases)

    # determine the attributes of the model's class
    _init_model_class_attributes(model_cls)

    check_pg_name(model_cls._table)

    # Transience
    if model_cls._transient and not model_cls._log_access:
        raise TypeError(
            "TransientModels must have log_access turned on, "
            "in order to implement their vacuum policy"
        )

    # update the registry after all checks have passed
    registry[name] = model_cls

    # mark all impacted models for setup
    for model_name in registry.descendants([name], '_inherit', '_inherits'):
        registry[model_name]._setup_done__ = False

    safe_checker.add_hook(model_cls, None)  # Optimization to serialize recordset(s) faster
    return model_cls


def _check_model_extension(model_cls: type[BaseModel], model_def: type[BaseModel]):
    """ Check whether ``model_cls`` can be extended with ``model_def``. """
    if model_def._table:
        raise TypeError(
            f"{model_def} cannot redefine _table while extending model {model_cls._name!r}. "
            "That class should either remove '_table', or set a different '_name'."
        )
    if model_cls._abstract and not model_def._abstract:
        raise TypeError(
            f"{model_def} transforms the abstract model {model_cls._name!r} into a non-abstract model. "
            "That class should either inherit from AbstractModel, or set a different '_name'."
        )
    if model_cls._transient != model_def._transient:
        if model_cls._transient:
            raise TypeError(
                f"{model_def} transforms the transient model {model_cls._name!r} into a non-transient model. "
                "That class should either inherit from TransientModel, or set a different '_name'."
            )
        else:
            raise TypeError(
                f"{model_def} transforms the model {model_cls._name!r} into a transient model. "
                "That class should either inherit from Model, or set a different '_name'."
            )


def _check_model_parent_extension(model_cls: type[BaseModel], model_def: type[BaseModel], parent_cls: type[BaseModel]):
    """ Check whether ``model_cls`` can inherit from ``parent_cls``. """
    if model_cls._abstract and not parent_cls._abstract:
        raise TypeError(
            f"In {model_def}, abstract model {model_cls._name!r} cannot inherit from non-abstract model {parent_cls._name!r}."
        )


def _init_model_class_attributes(model_cls: type[BaseModel]):
    """ Initialize model class attributes. """
    assert is_model_class(model_cls)

    model_cls._description = model_cls._name
    model_cls._table = model_cls._name.replace('.', '_')
    model_cls._log_access = model_cls._auto
    inherits = {}
    depends = {}

    for base in reversed(model_cls._base_classes__):
        if is_model_definition(base):
            # the following attributes are not taken from registry classes
            if model_cls._name not in base._inherit and not base._description:
                _logger.warning("The model %s has no _description", model_cls._name)
            model_cls._description = base._description or model_cls._description
            model_cls._table = base._table or model_cls._table
            model_cls._log_access = getattr(base, '_log_access', model_cls._log_access)

        inherits.update(base._inherits)

        for mname, fnames in base._depends.items():
            depends.setdefault(mname, []).extend(fnames)

    # avoid assigning an empty dict to save memory
    if inherits:
        model_cls._inherits = inherits
    if depends:
        model_cls._depends = depends

    # update _inherits_children of parent models
    registry = model_cls.pool
    for parent_name in model_cls._inherits:
        registry[parent_name]._inherits_children.add(model_cls._name)

    # recompute attributes of _inherit_children models
    for child_name in model_cls._inherit_children:
        _init_model_class_attributes(registry[child_name])

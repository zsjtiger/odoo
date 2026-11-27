"""Setup of the models of the registry: the models, their fields, and the inverses and the computed fields."""

from __future__ import annotations

import typing
import warnings
from collections import defaultdict, deque
from operator import attrgetter
from odoo.tools import OrderedSet
from odoo.tools.func import locked, reset_cached_properties
from odoo.tools.lru import LRU
from odoo.tools.misc import Collector
from odoo.tools.system.version_tag_reset import reset_classes_tp_versions_used
from odoo.orm.core.utils import SUPERUSER_ID
from odoo.orm.models import classes as model_classes

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from odoo.fields import Field
    from odoo.orm.database.sql_db import BaseCursor

from .base import Registry, _logger

def descendants(self, model_names: Iterable[str], *kinds: typing.Literal['_inherit', '_inherits']) -> OrderedSet[str]:
    """ Return the models corresponding to ``model_names`` and all those
    that inherit/inherits from them.
    """
    assert all(kind in ('_inherit', '_inherits') for kind in kinds)
    funcs = [attrgetter(kind + '_children') for kind in kinds]

    models: OrderedSet[str] = OrderedSet()
    queue = deque(model_names)
    while queue:
        model = self.get(queue.popleft())
        if model is None or model._name in models:
            continue
        models.add(model._name)
        for func in funcs:
            queue.extend(func(model))
    return models


@locked
def _setup_models__(self, cr: BaseCursor, model_names: Iterable[str] | None = None) -> None:  # noqa: PLW3201
    """ Perform the setup of models.
    This must be called after loading modules and before using the ORM.

    When given ``model_names``, it performs an incremental setup: only the
    models impacted by the given ``model_names`` and all the already-marked
    models will be set up. Otherwise, all models are set up.
    """
    from odoo.orm.models.environments import Environment  # noqa: PLC0415
    env = Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    transaction = env.transaction

    # Uninstall registry hooks. Because of the condition, this only happens
    # on a fully loaded registry, and not on a registry being loaded.
    if self.ready:
        transaction.will_change_registry()
        for model in env.values():
            model._unregister_hook()
        # clear cache to ensure consistency, we are in self.ready, so it
        # will signal the change anyways because the registry changes
        transaction.invalidate_ormcache('stable')
    else:
        # loading the registry, or running at_install tests
        # clear cache to ensure consistency, but do not signal it
        transaction.invalidate_ormcache('stable')
        for name, layer in transaction.ormcaches__.items():
            if layer.parent is None:
                layer.parent = LRU(999999)
                layer.update_parent()
                transaction._registry_caches__[name] = (transaction._registry_caches__[name][0], layer.parent)
        _logger.debug("skip signaling for previous invalidations")

    reset_cached_properties(self)

    # model classes on which to *not* recompute field_depends[_context]
    models_field_depends_done = set()

    if model_names is None:
        self.many2many_relations.clear()
        self.field_setup_dependents.clear()

        # mark all models for setup
        for model_cls in self.models.values():
            model_cls._setup_done__ = False

        self.field_depends.clear()
        self.field_depends_context.clear()

    else:
        # only mark impacted models for setup and invalidate related fields
        model_names_to_setup = self.descendants(model_names, '_inherit', '_inherits')
        for fields in self.many2many_relations.values():
            for pair in list(fields):
                if pair[0] in model_names_to_setup:
                    fields.discard(pair)

        for model_name in model_names_to_setup:
            self[model_name]._setup_done__ = False

        # recursively mark fields to re-setup
        todo = []
        for model_cls in self.models.values():
            if model_cls._custom:
                # custom models are going to be reloaded and set up below
                model_cls._setup_done__ = False
            if model_cls._setup_done__:
                models_field_depends_done.add(model_cls)
            elif not model_cls._abstract:
                todo.extend(model_cls._fields.values())

        done = set()
        for field in todo:
            if field in done:
                continue

            model_cls = self[field.model_name]
            if model_cls._setup_done__ and field._base_fields__:
                # the field has been created by model_classes._setup() as
                # Field(_base_fields__=...); restore it to force its setup
                name = field.name
                base_fields = field._base_fields__

                field.__dict__.clear()
                field.__init__(_base_fields__=base_fields)
                field._shareable = False
                field.__set_name__(model_cls, name)
                field._setup_done = False

                models_field_depends_done.discard(model_cls)

            elif model_cls._setup_done__ and field.related and field.manual:
                # manually-added related field (e.g. added via Studio) that has
                # no _base_fields__ so it cannot be partially reset; mark the
                # whole model for full re-setup so that setup_model_classes()
                # recreates the field pointing to the updated target field
                model_cls._setup_done__ = False
                models_field_depends_done.discard(model_cls)

            # partial invalidation of field_depends[_context]
            self.field_depends.pop(field, None)
            self.field_depends_context.pop(field, None)

            done.add(field)
            todo.extend(self.field_setup_dependents.pop(field, ()))

    self.many2one_company_dependents.clear()

    model_classes.setup_model_classes(env)

    # determine field_depends and field_depends_context
    for model_cls in self.models.values():
        if model_cls._abstract:
            continue
        if model_cls in models_field_depends_done:
            continue
        model = model_cls(env, (), ())
        for field in model._fields.values():
            depends, depends_context = field.get_depends(model)
            self.field_depends[field] = tuple(depends)
            self.field_depends_context[field] = tuple(depends_context)

    # clean the lazy_property again in case they are cached by another ongoing registry readonly request
    reset_cached_properties(self)

    # Reinstall registry hooks. Because of the condition, this only happens
    # on a fully loaded registry, and not on a registry being loaded.
    if self.ready:
        for model in env.values():
            model._register_hook()
        env.cr.flush()
        env.transaction.clear()
        self.check_null_constraints(env.cr)
    reset_classes_tp_versions_used([*self.values(), Registry])  # cpython optimisation


def field_inverses(self) -> Collector[Field, Field]:
    result = Collector()
    for model_cls in self.models.values():
        for field in model_cls._fields.values():
            if field.relational:
                field.setup_inverses(self, result)
    return result


def field_computed(self) -> dict[Field, list[Field]]:
    """ Return a dict mapping each field to the fields computed by the same method. """
    computed: dict[Field, list[Field]] = {}
    for model_name, Model in self.models.items():
        groups: defaultdict[Field, list[Field]] = defaultdict(list)
        for field in Model._fields.values():
            if field.compute:
                computed[field] = group = groups[field.compute]
                group.append(field)
        for fields in groups.values():
            if len(fields) < 2:
                continue
            if len({field.compute_sudo for field in fields}) > 1:
                fnames = ", ".join(field.name for field in fields)
                warnings.warn(
                    f"{model_name}: inconsistent 'compute_sudo' for computed fields {fnames}. "
                    f"Either set 'compute_sudo' to the same value on all those fields, or "
                    f"use distinct compute methods for sudoed and non-sudoed fields.",
                    stacklevel=1,
                )
            if len({field.precompute for field in fields}) > 1:
                fnames = ", ".join(field.name for field in fields)
                warnings.warn(
                    f"{model_name}: inconsistent 'precompute' for computed fields {fnames}. "
                    f"Either set all fields as precompute=True (if possible), or "
                    f"use distinct compute methods for precomputed and non-precomputed fields.",
                    stacklevel=1,
                )
            if len({field.store for field in fields}) > 1:
                fnames1 = ", ".join(field.name for field in fields if not field.store)
                fnames2 = ", ".join(field.name for field in fields if field.store)
                warnings.warn(
                    f"{model_name}: inconsistent 'store' for computed fields, "
                    f"accessing {fnames1} may recompute and update {fnames2}. "
                    f"Use distinct compute methods for stored and non-stored fields.",
                    stacklevel=1,
                )
    return computed

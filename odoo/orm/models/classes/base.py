"""The model classes: the helpers of the model definitions and the model classes, and the cache of the shared fields."""

from __future__ import annotations

import typing
import weakref
from odoo.orm import models

if typing.TYPE_CHECKING:
    from odoo.fields import Field


SHARED_FIELD_CACHE: weakref.WeakValueDictionary[tuple[str, tuple[Field, ...]], Field] = weakref.WeakValueDictionary()
"""Cache of shared registry field instances keyed by (model_name, definition_fields_tuple)."""


# THE MODEL DEFINITIONS, MODEL CLASSES, AND MODEL INSTANCES
#
# The framework deals with two kinds of classes for models: the "model
# definitions" and the "model classes".
#
# The "model definitions" are the classes defined in modules source code: they
# define models and extend them.  Those classes are essentially "static", for
# whatever that means in Python.  The only exception is custom models: their
# model definition is created dynamically.
#
# The "model classes" are the ones you find in the registry.  The recordsets of
# a model actually are instances of its model class.  The "model class" of a
# model is created dynamically when the registry is built.  It inherits (in the
# Python sense) from all the model definitions of the model, and possibly other
# model classes (when the model inherits from another model).  It also carries
# model metadata inferred from its parent classes.
#
#
# THE MODEL CLASSES
#
# In the simplest case, a model class inherits from all the classes that define
# the model in a flat hierarchy.  Consider the definitions of model 'a' below.
# The model class of 'a' inherits from the model definitions A1, A2, A3, in
# reverse order, to match the expected overriding order.  The model class
# carries inferred metadata that is shared between all the recordsets of that
# model for a given registry.
#
#       class A(Model):  # A1                 Model
#           _name = 'a'                       / | \
#                                            A3 A2 A1   <- model definitions
#       class A(Model):  # A2                 \ | /
#           _inherit = 'a'                      a       <- model class: registry['a']
#                                               |
#       class A(Model):  # A3                records    <- model instances, like env['a']
#           _inherit = 'a'
#
# Note that when the model inherits from another model, we actually make the
# model classes inherit from each other, so that extensions to an inherited
# model are visible in the model class of the child model, like in the
# following example.
#
#       class A(Model):  # A1
#           _name = 'a'                       Model
#                                            / / \ \
#       class B(Model):  # B1               / /   \ \
#           _name = 'b'                    / A2   A1 \
#                                         B2  \   /  B1
#       class B(Model):  # B2              \   \ /   /
#           _inherit = ['a', 'b']           \   a   /
#                                            \  |  /
#       class A(Model):  # A2                 \ | /
#           _inherit = 'a'                      b
#
# To be more explicit, the parent classes of model 'a' are (A2, A1), and the
# ones of model 'b' are (B2, a, B1).  Consequently, the MRO of model 'a' is
# [a, A2, A1, Model] while the MRO of 'b' is [b, B2, a, A2, A1, B1, Model].
#
#
# THE FIELDS OF A MODEL
#
# The fields of a model are given by the model's definitions, inherited models
# ('_inherit' and '_inherits') and other parties, like custom fields. Note that
# a field can be partially overridden when it appears on several definitions of
# its model.  In that case, the field's final definition depends on the
# presence or absence of each model definition, which itself depends on the
# modules loaded in the registry.
#
# By design, the model class has access to all the fields on its model
# definitions.  When possible, the field is used directly from its model
# definition.  There are a number of cases where the field cannot be used
# directly:
#  - the field is related (and bits may not be shared);
#  - the field is overridden on model definitions;
#  - the field is defined on another model (and accessible by mixin).
#
# The last case prevents sharing the field across registries, because the field
# object is specific to a model, and is used as a key in several key
# dictionaries, like the record cache and pending computations.
#
# Setting up a field on its model definition helps saving memory and time.
# Indeed, when sharing is possible, the field's setup is almost entirely done
# where the field was defined.  It is thus done when the model definition was
# created, and it may be reused across registries.
#
# In the example below, the field 'foo' appears once on its model definition.
# Assuming that it is not related, that field can be set up directly on its
# model definition.  If the model appears in several registries, the
# field 'foo' is effectively shared across registries.
#
#       class A1(Model):                      Model
#           _name = 'a'                        / \
#           foo = ...                         /   \
#           bar = ...                       A2     A1
#                                            bar    foo, bar
#       class A2(Model):                      \   /
#           _inherit = 'a'                     \ /
#           bar = ...                           a
#                                                bar
#
# On the other hand, the field 'bar' is overridden in its model definitions.  In
# that case, the framework recreates the field on the model class, which is
# never shared across registries.  The field's setup will be based on its
# definitions, and will thus not be shared across registries.
#
# The so-called magic fields ('id', 'display_name', ...) used to be added on
# model classes.  But doing so prevents them from being shared.  So instead,
# we add them on definition classes that define a model without extending it.
# This increases the number of fields that are shared across registries.


def discardattr(obj: object, key: str) -> None:
    """ Perform a ``delattr(obj, key)`` but without crashing if ``key`` is not present. """
    try:  # noqa: SIM105
        delattr(obj, key)
    except AttributeError:
        pass


def is_model_definition(cls: type) -> bool:
    """ Return whether ``cls`` is a model definition class. """
    return isinstance(cls, models.MetaModel) and getattr(cls, 'pool', None) is None


def is_model_class(cls: type) -> bool:
    """ Return whether ``cls`` is a model registry class. """
    return getattr(cls, 'pool', None) is not None

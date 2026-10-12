# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The model classes: the registration of the model definitions, the setup of the model classes, the manual models and the fields of the classes. The names are re-exported here."""

from __future__ import annotations

import logging
import typing
import weakref
from collections import defaultdict
from types import MappingProxyType
from odoo.orm import models
from odoo.orm import fields  # must be imported after models
from odoo.orm.core.utils import check_pg_name
from odoo.exceptions import ValidationError
from odoo.tools import (
    OrderedSet,
    LastOrderedSet,
    frozendict,
    sql,
)
from odoo.tools.safe_eval import safe_checker
from odoo.tools.text.translate import FIELD_TRANSLATE

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.fields import Field
    from odoo.models import BaseModel
    from odoo.modules.registry import Registry

from .base import SHARED_FIELD_CACHE, discardattr, is_model_class, is_model_definition
from .registration import _check_model_extension, _check_model_parent_extension, _init_model_class_attributes, add_to_registry
from .fields import add_field, pop_field
from .setup import _add_inherited_fields, _check_inherits, _prepare_setup, _setup, _setup_fields, setup_model_classes
from .manual import _add_manual_fields, _add_manual_models

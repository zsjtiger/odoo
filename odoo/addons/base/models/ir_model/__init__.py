# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The models of the registry: the models, their fields, inheritances, selections, constraints, relations and external identifiers. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import ACCESS_ERROR_GROUPS, ACCESS_ERROR_HEADER, ACCESS_ERROR_NOGROUP, ACCESS_ERROR_RESOLUTION, MODULE_UNINSTALL_FLAG, RE_ORDER_FIELDS, SAFE_EVAL_BASE, _lt, field_xmlid, make_compute, mark_modified, model_xmlid, query_insert, query_update, select_en, selection_xmlid, upsert_en
from .base import Base, Unknown
from .model import IrModel
from .field import FIELD_INDEX_TYPES, FIELD_TYPES, IrModelFields
from .inherit import IrModelInherit
from .field_selection import IrModelFieldsSelection
from .constraint import IrModelConstraint
from .relation import IrModelRelation
from .data import IrModelData

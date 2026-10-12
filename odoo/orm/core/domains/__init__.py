# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The domains of the models, split by concern. The names are re-exported here."""

from .constants import CONDITION_OPERATORS, INTERNAL_CONDITION_OPERATORS, MAX_OPTIMIZE_ITERATIONS, NEGATIVE_CONDITION_OPERATORS, OptimizationLevel, STANDARD_CONDITION_OPERATORS, _FALSE_LEAF, _INVERSE_INEQUALITY, _INVERSE_OPERATOR, _TRUE_LEAF
from .registry import _MERGE_OPTIMIZATIONS, _OPTIMIZATIONS_FOR, field_type_optimization, nary_optimization, operator_optimization
from .base import ANY_TYPES, Domain
from .boolean import DomainBool, _FALSE_DOMAIN, _TRUE_DOMAIN
from .negation import DomainNot
from .nary import DomainAnd, DomainNary, DomainOr, _optimize_nary_sort_key, intersection, union
from .condition import DomainCondition, _optimize_boolean_in_all
from .custom import DomainCustom

# the optimizations register themselves on import: keep this import last
from . import optimizations
from .optimizations.merge import nary_condition_optimization

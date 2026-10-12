# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The domains of the models, split by concern. The names are re-exported here."""

from .constants import CONDITION_OPERATORS, INTERNAL_CONDITION_OPERATORS, MAX_OPTIMIZE_ITERATIONS, NEGATIVE_CONDITION_OPERATORS, OptimizationLevel, STANDARD_CONDITION_OPERATORS, _FALSE_LEAF, _INVERSE_INEQUALITY, _INVERSE_OPERATOR, _TRUE_LEAF
from .registry import _MERGE_OPTIMIZATIONS, _OPTIMIZATIONS_FOR, field_type_optimization, nary_optimization, operator_optimization
from .classes import ANY_TYPES, Domain, DomainAnd, DomainBool, DomainCondition, DomainCustom, DomainNary, DomainNot, DomainOr, _FALSE_DOMAIN, _TRUE_DOMAIN, _optimize_boolean_in_all, _optimize_nary_sort_key, intersection, union

# the optimizations register themselves on import: keep this import last
from . import optimizations
from .optimizations.merge import nary_condition_optimization

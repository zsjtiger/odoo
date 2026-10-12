"""Registration of the optimizations of the conditions and of the n-ary domains."""

from __future__ import annotations

import collections
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection
    from odoo.orm.models import BaseModel
    from .classes import Domain, DomainCondition, DomainNary
    ConditionOptimization = Callable[[DomainCondition, BaseModel], Domain]
    MergeOptimization = Callable[[type[DomainNary], list[Domain], BaseModel], list[Domain]]

from .constants import CONDITION_OPERATORS, OptimizationLevel

_OPTIMIZATIONS_FOR: dict[OptimizationLevel, dict[str, list[ConditionOptimization]]] = {
    level: collections.defaultdict(list) for level in OptimizationLevel if level != OptimizationLevel.NONE}


_MERGE_OPTIMIZATIONS: list[MergeOptimization] = list()


def operator_optimization(operators: Collection[str], level: OptimizationLevel = OptimizationLevel.BASIC):
    """Register a condition operator optimization for (condition, model)"""
    assert operators, "Missing operator to register"
    CONDITION_OPERATORS.update(operators)

    def register(optimization: ConditionOptimization):
        mapping = _OPTIMIZATIONS_FOR[level]
        for operator in operators:  # noqa: F402
            mapping[operator].append(optimization)
        return optimization

    return register


def field_type_optimization(field_types: Collection[str], level: OptimizationLevel = OptimizationLevel.BASIC):
    """Register a condition optimization by field type for (condition, model)"""
    def register(optimization: ConditionOptimization):
        mapping = _OPTIMIZATIONS_FOR[level]
        for field_type in field_types:
            mapping[field_type].append(optimization)
        return optimization

    return register


def nary_optimization(optimization: MergeOptimization):
    """Register an optimization to a list of children of an nary domain.

    The function will take an iterable containing optimized children of a
    n-ary domain and returns *optimized* domains.

    Note that you always need to optimize both AND and OR domains. It is always
    possible because if you can optimize `a & b` then you can optimize `a | b`
    because it is optimizing `~(~a & ~b)`. Since operators can be negated,
    all implementations of optimizations are implemented in a mirrored way:
    `(optimize AND) if some_condition == cls.ZERO.value else (optimize OR)`.

    The optimization of nary domains starts by optimizing the children,
    then sorts them by (field, operator_type, operator) where operator type
    groups similar operators together.
    """
    _MERGE_OPTIMIZATIONS.append(optimization)
    return optimization

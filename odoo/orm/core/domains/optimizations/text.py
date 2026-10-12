"""Optimizations of the conditions on text."""

from __future__ import annotations

import typing
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    pass

from ..classes import Domain, DomainCondition
from ..constants import CONDITION_OPERATORS, NEGATIVE_CONDITION_OPERATORS
from ..registry import operator_optimization

@operator_optimization([op for op in CONDITION_OPERATORS if op.endswith('like')])
def _optimize_like_str(condition, model):
    """Validate value for pattern matching, must be a str"""
    value = condition.value
    if not value:
        # =like matches only empty string (inverse the condition)
        result = (condition.operator in NEGATIVE_CONDITION_OPERATORS) == ('=' in condition.operator)
        # relational and non-relation fields behave differently
        if condition._field(model).relational or '=' in condition.operator:
            return DomainCondition(condition.field_expr, '!=' if result else '=', False)
        return Domain(result)
    if isinstance(value, str):
        return condition
    if isinstance(value, SQL):
        condition._raise("Use Domain.custom instead of SQL", error=TypeError)
    if '=' in condition.operator:
        condition._raise("The pattern to match must be a string", error=TypeError)
    return DomainCondition(condition.field_expr, condition.operator, str(value))

"""Operators of the domains, their negations and the optimization levels."""

from __future__ import annotations

import enum
import functools
import typing

if typing.TYPE_CHECKING:
    pass


STANDARD_CONDITION_OPERATORS = frozenset([
    'any', 'not any',
    'any!', 'not any!',
    'in', 'not in',
    '<', '>', '<=', '>=',
    'like', 'not like',
    'ilike', 'not ilike',
    '=like', 'not =like',
    '=ilike', 'not =ilike',
])


CONDITION_OPERATORS = set(STANDARD_CONDITION_OPERATORS)  # modifiable (for optimizations only)


INTERNAL_CONDITION_OPERATORS = frozenset(('any!', 'not any!'))


NEGATIVE_CONDITION_OPERATORS = {
    'not any': 'any',
    'not any!': 'any!',
    'not in': 'in',
    'not like': 'like',
    'not ilike': 'ilike',
    'not =like': '=like',
    'not =ilike': '=ilike',
    '!=': '=',
}


_INVERSE_OPERATOR = {
    # from NEGATIVE_CONDITION_OPERATORS
    'not any': 'any',
    'not any!': 'any!',
    'not in': 'in',
    'not like': 'like',
    'not ilike': 'ilike',
    'not =like': '=like',
    'not =ilike': '=ilike',
    '!=': '=',
    # positive to negative
    'any': 'not any',
    'any!': 'not any!',
    'in': 'not in',
    'like': 'not like',
    'ilike': 'not ilike',
    '=like': 'not =like',
    '=ilike': 'not =ilike',
    '=': '!=',
}


_INVERSE_INEQUALITY = {
    '<': '>=',
    '>': '<=',
    '>=': '<',
    '<=': '>',
}


_TRUE_LEAF = (1, '=', 1)


_FALSE_LEAF = (0, '=', 1)


class OptimizationLevel(enum.IntEnum):
    """Indicator whether the domain was optimized."""
    NONE = 0
    BASIC = enum.auto()
    DYNAMIC_VALUES = enum.auto()
    FULL = enum.auto()

    @functools.cached_property
    def next_level(self):
        assert self is not OptimizationLevel.FULL, "FULL level is the last one"
        return OptimizationLevel(int(self) + 1)


MAX_OPTIMIZE_ITERATIONS = 1000

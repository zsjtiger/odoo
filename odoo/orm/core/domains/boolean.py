"""The constant domains: TRUE and FALSE."""

from __future__ import annotations

import typing
from odoo.tools import SQL
from odoo.orm.database.query import TableSQL
from .constants import OptimizationLevel, _FALSE_LEAF, _TRUE_LEAF

if typing.TYPE_CHECKING:
    pass

from .base import Domain

class DomainBool(Domain):
    """Constant domain: True/False

    It is NOT considered as a condition and these constants are removed
    from nary domains.
    """
    __slots__ = ('value',)
    value: bool

    def __new__(cls, value: bool):
        """Create a constant domain."""
        self = object.__new__(cls)
        object.__setattr__(self, 'value', value)
        object.__setattr__(self, '_opt_level', OptimizationLevel.FULL)
        return self

    def __eq__(self, other):
        return self is other  # because this class has two instances only

    def is_true(self) -> bool:
        return self.value

    def is_false(self) -> bool:
        return not self.value

    def __invert__(self):
        return _FALSE_DOMAIN if self.value else _TRUE_DOMAIN

    def __and__(self, other):
        if isinstance(other, Domain):
            return other if self.value else self
        return NotImplemented

    def __or__(self, other):
        if isinstance(other, Domain):
            return self if self.value else other
        return NotImplemented

    def __iter__(self):
        yield _TRUE_LEAF if self.value else _FALSE_LEAF

    def _as_predicate(self, records):
        return lambda _: self.value

    def _to_sql(self, table: TableSQL) -> SQL:
        return SQL("TRUE") if self.value else SQL("FALSE")


_TRUE_DOMAIN = DomainBool(True)


_FALSE_DOMAIN = DomainBool(False)

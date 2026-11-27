"""The negation of a domain."""

from __future__ import annotations

import typing
from odoo.tools import SQL
from odoo.orm.database.query import TableSQL
from .constants import OptimizationLevel

if typing.TYPE_CHECKING:
    from odoo.orm.models import BaseModel

from .base import Domain

class DomainNot(Domain):
    """Negation domain, contains a single child"""
    OPERATOR: typing.ClassVar[str] = '!'

    __slots__ = ('child',)
    child: Domain

    def __new__(cls, child: Domain):
        """Create a domain which is the inverse of the child."""
        self = object.__new__(cls)
        object.__setattr__(self, 'child', child)
        object.__setattr__(self, '_opt_level', OptimizationLevel.NONE)
        return self

    def __invert__(self):
        return self.child

    def __iter__(self):
        yield self.OPERATOR
        yield from self.child

    def iter_conditions(self):
        yield from self.child.iter_conditions()

    def map_conditions(self, function) -> Domain:
        return ~(self.child.map_conditions(function))

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        return self.child._optimize(model, level)._negate(model)

    def __eq__(self, other):
        return self is other or (isinstance(other, DomainNot) and self.child == other.child)

    def _as_predicate(self, records):
        predicate = self.child._as_predicate(records)
        return lambda rec: not predicate(rec)

    def _to_sql(self, table: TableSQL) -> SQL:
        return SQL("(%s) IS NOT TRUE", self.child._to_sql(table))

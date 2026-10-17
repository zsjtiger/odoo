"""The custom domains: the SQL, the predicate and the optimization are provided by the caller."""

from __future__ import annotations

import typing
from odoo.tools import SQL
from odoo.orm.database.query import Query, TableSQL
from .constants import OptimizationLevel

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from odoo.orm.models import BaseModel

from .base import Domain
from .condition import DomainCondition

class DomainCustom(Domain):
    """Domain condition that generates directly SQL and possibly a ``filtered`` predicate."""
    __slots__ = ('_filtered', '_optimize_func', '_sql')

    _filtered: Callable[[BaseModel], bool] | None
    _optimize_func: Callable[[DomainCustom, BaseModel], Domain] | None
    _sql: Callable[[BaseModel, str, Query], SQL] | None

    def __new__(
        cls,
        sql: Callable[[TableSQL], SQL] | None = None,
        filtered: Callable[[BaseModel], bool] | None = None,
        optimize_func: Callable[[DomainCustom, BaseModel], Domain] | None = None,
    ):
        """Create a new domain.

        :param to_sql: callable(model, alias, query) that implements ``_to_sql``
                       which is used to generate the query for searching
        :param predicate: callable(record) that checks whether a record is kept
                          when filtering (``Model.filtered``)
        :param optimize_func: callable(custom_domain, model) when set this
                              domain is at dynamic level and can be fully
                              optimized by that function
        """
        assert sql or optimize_func, "Need optimization or sql function"
        self = object.__new__(cls)
        object.__setattr__(self, '_sql', sql)
        object.__setattr__(self, '_filtered', filtered)
        object.__setattr__(self, '_optimize_func', optimize_func)
        object.__setattr__(self, '_opt_level', OptimizationLevel.FULL if optimize_func is None else OptimizationLevel.DYNAMIC_VALUES)
        return self

    def _optimize_step(self, model, level):
        if level == OptimizationLevel.FULL and self._optimize_func:
            return self._optimize_func(self, model)
        return self

    def _as_predicate(self, records):
        if self._filtered is not None:
            return self._filtered
        # by default, run the SQL query on accessible records
        query = records._filtered_access('read')._as_query(ordered=False)
        if query.is_empty():
            return Domain.FALSE._as_predicate(records)
        query.add_where(self._to_sql(query.table))
        return DomainCondition('id', 'any!', query)._as_predicate(records)

    def __eq__(self, other):
        return (
            isinstance(other, DomainCustom)
            and self._sql == other._sql
            and self._filtered == other._filtered
            and self._optimize_func == other._optimize_func
        )

    def __iter__(self):
        yield self

    def __repr__(self):
        return object.__repr__(self)

    def _to_sql(self, table: TableSQL) -> SQL:
        assert self._sql is not None, \
            f"Must fully optimize before generating the query {self}"
        return self._sql(table)

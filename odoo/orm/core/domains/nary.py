"""The n-ary domains (AND and OR) and their helpers: the flattening, the sorting and the set operations."""

from __future__ import annotations

import functools
import itertools
import operator
import typing
from odoo.tools import SQL, OrderedSet, classproperty
from odoo.orm.database.query import TableSQL
from .constants import NEGATIVE_CONDITION_OPERATORS, OptimizationLevel
from .registry import _MERGE_OPTIMIZATIONS

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from odoo.orm.models import BaseModel

from .base import Domain
from .boolean import DomainBool, _FALSE_DOMAIN, _TRUE_DOMAIN
from .condition import DomainCondition

class DomainNary(Domain):
    """Domain for a nary operator: AND or OR with multiple children"""
    OPERATOR: typing.ClassVar[str]
    OPERATOR_SQL: typing.ClassVar[SQL] = SQL(" ??? ")
    ZERO: typing.ClassVar[DomainBool] = _FALSE_DOMAIN  # default for lint checks

    __slots__ = ('children',)
    children: tuple[Domain, ...]

    def __new__(cls, children: tuple[Domain, ...]):
        """Create the n-ary domain with at least 2 conditions."""
        assert len(children) >= 2
        self = object.__new__(cls)
        object.__setattr__(self, 'children', children)
        object.__setattr__(self, '_opt_level', OptimizationLevel.NONE)
        return self

    @classmethod
    def apply(cls, items: Iterable[Domain]) -> Domain:
        """Return the result of combining AND/OR to a collection of domains."""
        children = cls._flatten(items)
        if len(children) == 1:
            return children[0]
        return cls(tuple(children))

    @classmethod
    def _flatten(cls, children: Iterable[Domain]) -> list[Domain]:
        """Return an equivalent list of domains with respect to the boolean
        operation of the class (AND/OR).  Boolean subdomains are simplified,
        and subdomains of the same class are flattened into the list.
        The returned list is never empty.
        """
        result: list[Domain] = []
        for child in children:
            if isinstance(child, DomainBool):
                if child != cls.ZERO:
                    return [child]
            elif isinstance(child, cls):
                result.extend(child.children)  # same class, flatten
            else:
                result.append(child)
        return result or [cls.ZERO]

    def __iter__(self):
        yield from itertools.repeat(self.OPERATOR, len(self.children) - 1)
        for child in self.children:
            yield from child

    def __eq__(self, other):
        return self is other or (
            isinstance(other, DomainNary)
            and self.OPERATOR == other.OPERATOR
            and self.children == other.children
        )

    @classproperty
    def INVERSE(cls) -> type[DomainNary]:
        """Return the inverted nary type, AND/OR"""
        raise NotImplementedError

    def __invert__(self):
        return self.INVERSE(tuple(~child for child in self.children))

    def _negate(self, model):
        return self.INVERSE(tuple(child._negate(model) for child in self.children))

    def iter_conditions(self):
        for child in self.children:
            yield from child.iter_conditions()

    def map_conditions(self, function) -> Domain:
        return self.apply(child.map_conditions(function) for child in self.children)

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        # optimize children
        children = self._flatten(child._optimize(model, level) for child in self.children)
        size = len(children)
        if size > 1:
            # nary-optimizations are independent of the level, so if BASIC was
            # performed and all children are exactly the same, there is no need
            # to try to merge them again
            if (
                level > OptimizationLevel.BASIC
                and len(self.children) == size
                and all(map(operator.is_, self.children, children))
            ):
                return self
            # sort children in order to ease their grouping by field and operator
            children.sort(key=_optimize_nary_sort_key)
            # run optimizations until some merge happens
            cls = type(self)
            for merge in _MERGE_OPTIMIZATIONS:
                children = merge(cls, children, model)
                if len(children) < size:
                    break
            else:
                # if no change, skip creation of a new object
                if len(self.children) == len(children) and all(map(operator.is_, self.children, children)):
                    return self
        return self.apply(children)

    def _to_sql(self, table: TableSQL) -> SQL:
        return SQL("(%s)", self.OPERATOR_SQL.join(
            child._to_sql(table) for child in self.children
        ))


class DomainAnd(DomainNary):
    """Domain: AND with multiple children"""
    __slots__ = ()
    OPERATOR = '&'
    OPERATOR_SQL = SQL(" AND ")
    ZERO = _TRUE_DOMAIN

    @classproperty
    def INVERSE(cls) -> type[DomainNary]:
        return DomainOr

    def __and__(self, other):
        # simple optimization to append children
        if isinstance(other, DomainAnd):
            return DomainAnd(self.children + other.children)
        return super().__and__(other)

    def _as_predicate(self, records):
        # For the sake of performance, the list of predicates is generated
        # lazily with a generator, which is memoized with `itertools.tee`
        all_predicates = (child._as_predicate(records) for child in self.children)

        def and_predicate(record):
            nonlocal all_predicates
            all_predicates, predicates = itertools.tee(all_predicates)
            return all(pred(record) for pred in predicates)

        return and_predicate


class DomainOr(DomainNary):
    """Domain: OR with multiple children"""
    __slots__ = ()
    OPERATOR = '|'
    OPERATOR_SQL = SQL(" OR ")
    ZERO = _FALSE_DOMAIN

    @classproperty
    def INVERSE(cls) -> type[DomainNary]:
        return DomainAnd

    def __or__(self, other):
        # simple optimization to append children
        if isinstance(other, DomainOr):
            return DomainOr(self.children + other.children)
        return super().__or__(other)

    def _as_predicate(self, records):
        # For the sake of performance, the list of predicates is generated
        # lazily with a generator, which is memoized with `itertools.tee`
        all_predicates = (child._as_predicate(records) for child in self.children)

        def or_predicate(record):
            nonlocal all_predicates
            all_predicates, predicates = itertools.tee(all_predicates)
            return any(pred(record) for pred in predicates)

        return or_predicate


def _optimize_nary_sort_key(domain: Domain) -> tuple[str, str, str]:
    """Sorting key for nary domains so that similar operators are grouped together.

    1. Field name (non-simple conditions are sorted at the end)
    2. Operator type (equality, inequality, existence, string comparison, other)
    3. Operator

    Sorting allows to have the same optimized domain for equivalent conditions.
    For debugging, it eases to find conditions on fields.
    The generated SQL will be ordered by field name so that database caching
    can be applied more frequently.
    """
    if isinstance(domain, DomainCondition):
        # group the same field and same operator together
        operator = domain.operator
        positive_op = NEGATIVE_CONDITION_OPERATORS.get(operator, operator)
        if positive_op == 'in':
            order = "0in"
        elif positive_op == 'any':
            order = "1any"
        elif positive_op == 'any!':
            order = "2any"
        elif positive_op.endswith('like'):
            order = "like"
        else:
            order = positive_op
        return domain.field_expr, order, operator
    elif hasattr(domain, 'OPERATOR') and isinstance(domain.OPERATOR, str):
        # in python; '~' > any letter
        return '~', '', domain.OPERATOR
    else:
        return '~', '~', domain.__class__.__name__


def intersection(sets: list[OrderedSet]) -> OrderedSet:
    """Intersection of a list of OrderedSets"""
    return functools.reduce(operator.and_, sets)


def union(sets: list[OrderedSet]) -> OrderedSet:
    """Union of a list of OrderedSets"""
    return OrderedSet(elem for s in sets for elem in s)

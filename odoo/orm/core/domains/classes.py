"""The domain classes: the base, the booleans, the negation, the n-ary domains, the custom domains and the conditions."""

from __future__ import annotations

import functools
import itertools
import logging
import operator
import types
import typing
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, OrderedSet, classproperty
from odoo.orm.core.identifiers import NewId
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import COLLECTION_TYPES, parse_field_expr

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from odoo.orm.fields import Field
    from odoo.orm.models import BaseModel

from .constants import CONDITION_OPERATORS, INTERNAL_CONDITION_OPERATORS, MAX_OPTIMIZE_ITERATIONS, NEGATIVE_CONDITION_OPERATORS, OptimizationLevel, STANDARD_CONDITION_OPERATORS, _FALSE_LEAF, _INVERSE_INEQUALITY, _INVERSE_OPERATOR, _TRUE_LEAF
from .registry import _MERGE_OPTIMIZATIONS, _OPTIMIZATIONS_FOR, field_type_optimization

_logger = logging.getLogger('odoo.domains')


class Domain:
    """Representation of a domain as an AST.
    """
    # Domain is an abstract class (ABC), but not marked as such
    # because we overwrite __new__ so typechecking for abstractmethod is incorrect.
    # We do this so that we can use the Domain as both a factory for multiple
    # types of domains, while still having `isinstance` working for it.
    __slots__ = ('_opt_level',)
    _opt_level: OptimizationLevel

    def __new__(cls, *args, internal: bool = False):
        """Build a domain AST.

        ```
        Domain([('a', '=', 5), ('b', '=', 8)])
        Domain('a', '=', 5) & Domain('b', '=', 8)
        Domain.AND([Domain('a', '=', 5), *other_domains, Domain.TRUE])
        ```

        If we have one argument, it is a `Domain`, or a list representation, or a bool.
        In case we have multiple ones, there must be 3 of them:
        a field (str), the operator (str) and a value for the condition.

        By default, the special operators ``'any!'`` and ``'not any!'`` are
        allowed in domain conditions (``Domain('a', 'any!', dom)``) but not in
        domain lists (``Domain([('a', 'any!', dom)])``).
        """
        if len(args) > 1:
            if isinstance(args[0], str):
                return DomainCondition(*args).checked()
            # special cases like True/False constants
            if args == _TRUE_LEAF:
                return _TRUE_DOMAIN
            if args == _FALSE_LEAF:
                return _FALSE_DOMAIN
            raise TypeError(f"Domain() invalid arguments: {args!r}")

        arg = args[0]
        if isinstance(arg, Domain):
            return arg
        if arg is True or arg == []:
            return _TRUE_DOMAIN
        if arg is False:
            return _FALSE_DOMAIN
        if arg is NotImplemented:
            raise NotImplementedError

        # parse as a list
        # perf: do this inside __new__ to avoid calling function that return
        # a Domain which would call implicitly __init__
        if not isinstance(arg, (list, tuple)):
            raise TypeError(f"Domain() invalid argument type for domain: {arg!r}")
        stack: list[Domain] = []
        try:
            for item in reversed(arg):
                if isinstance(item, (tuple, list)) and len(item) == 3:
                    if internal:
                        # process subdomains when processing internal operators
                        if item[1] in ('any', 'any!', 'not any', 'not any!') and isinstance(item[2], (list, tuple)):
                            item = (item[0], item[1], Domain(item[2], internal=True))
                    elif item[1] in INTERNAL_CONDITION_OPERATORS:
                        # internal operators are not accepted
                        raise ValueError(f"Domain() invalid item in domain: {item!r}")
                    stack.append(Domain(*item))
                elif item == DomainAnd.OPERATOR:
                    stack.append(stack.pop() & stack.pop())
                elif item == DomainOr.OPERATOR:
                    stack.append(stack.pop() | stack.pop())
                elif item == DomainNot.OPERATOR:
                    stack.append(~stack.pop())
                elif isinstance(item, Domain):
                    stack.append(item)
                else:
                    raise ValueError(f"Domain() invalid item in domain: {item!r}")
            # keep the order and simplify already
            if len(stack) == 1:
                return stack[0]
            return Domain.AND(reversed(stack))
        except IndexError:
            raise ValueError(f"Domain() malformed domain {arg!r}")

    @classproperty
    def TRUE(cls) -> Domain:
        return _TRUE_DOMAIN

    @classproperty
    def FALSE(cls) -> Domain:
        return _FALSE_DOMAIN

    NEGATIVE_OPERATORS = types.MappingProxyType(NEGATIVE_CONDITION_OPERATORS)

    @staticmethod
    def custom(
        *,
        to_sql: Callable[[TableSQL], SQL] | None = None,
        predicate: Callable[[BaseModel], bool] | None = None,
        optimize: Callable[[DomainCustom, BaseModel], Domain] | None = None,
    ) -> DomainCustom:
        """Create a custom domain.

        :param to_sql: callable(model, alias, query) that returns the SQL
        :param optimize: callable(custom_domain, model) that runs for full
                         optimization in order to translate to a normal domain
        :param predicate: callable(record) that checks whether a record is kept
                          when filtering
        """
        return DomainCustom(to_sql, predicate, optimize)

    @staticmethod
    def AND(items: Iterable) -> Domain:
        """Build the conjuction of domains: (item1 AND item2 AND ...)"""
        return DomainAnd.apply(Domain(item) for item in items)

    @staticmethod
    def OR(items: Iterable) -> Domain:
        """Build the disjuction of domains: (item1 OR item2 OR ...)"""
        return DomainOr.apply(Domain(item) for item in items)

    def __setattr__(self, name, value):
        raise TypeError("Domain objects are immutable")

    def __delattr__(self, name):
        raise TypeError("Domain objects are immutable")

    def __and__(self, other):
        """Domain & Domain"""
        if isinstance(other, DomainBool):
            return other & self
        if isinstance(other, Domain):
            return DomainAnd.apply((self, other))
        return NotImplemented

    def __or__(self, other):
        """Domain | Domain"""
        if isinstance(other, DomainBool):
            return other | self
        if isinstance(other, Domain):
            return DomainOr.apply((self, other))
        return NotImplemented

    def __invert__(self):
        """~Domain"""
        return DomainNot(self)

    def _negate(self, model: BaseModel) -> Domain:
        """Apply (propagate) negation onto this domain. """
        return ~self

    def __add__(self, other):
        """Domain + [...]

        For backward-compatibility of domain composition.
        Concatenate as lists.
        If we have two domains, equivalent to '&'.
        """
        # TODO deprecate this possibility so that users combine domains correctly
        if isinstance(other, Domain):
            return self & other
        if not isinstance(other, list):
            raise TypeError('Domain() can concatenate only lists')
        return list(self) + other

    def __radd__(self, other):
        """Commutative definition of *+*"""
        # TODO deprecate this possibility so that users combine domains correctly
        # we are pre-pending, return a list
        # because the result may not be normalized
        return other + list(self)

    def __bool__(self):
        """Indicate that the domain is not true.

        For backward-compatibility, only the domain [] was False. Which means
        that the TRUE domain is falsy and others are truthy.
        """
        # TODO deprecate this usage, we have is_true() and is_false()
        # warnings.warn("Do not use bool() on Domain, use is_true() or is_false() instead", DeprecationWarning)
        return not self.is_true()

    def __eq__(self, other):
        raise NotImplementedError

    def __hash__(self):
        raise NotImplementedError("Domains are not hashable")

    def __iter__(self):
        """For-backward compatibility, return the polish-notation domain list"""
        yield from ()
        raise NotImplementedError

    def __reversed__(self):
        """For-backward compatibility, reversed iter"""
        return reversed(list(self))

    def __repr__(self) -> str:
        # return representation of the object as the old-style list
        return repr(list(self))

    def is_true(self) -> bool:
        """Return whether self is TRUE"""
        return False

    def is_false(self) -> bool:
        """Return whether self is FALSE"""
        return False

    def is_condition(self,
        field_expr: str = '',
        operator: str | tuple[str] = (),
        value: type | tuple[type] = (),
    ) -> bool:
        """Return whether this domain is a simple condition, and whether it
        matches the ``field_expr`` (if given), the ``operator`` (if given), and
        the ``value`` type (if given).
        """
        return False

    def iter_conditions(self) -> Iterable[DomainCondition]:
        """Yield simple conditions of the domain"""
        yield from ()

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        """Map a function to each condition and return the combined result"""
        return self

    def validate(self, model: BaseModel) -> None:
        """Validates that the current domain is correct or raises an exception"""
        # just execute the optimization code that goes through all the fields
        # the search domain is set to False to avoid performing searches
        self.optimize_full(model, search_domain=Domain.FALSE)._to_sql(Query(model).table)

    def _as_predicate[M: BaseModel](self, records: M) -> Callable[[M], bool]:
        """Return a predicate function from the domain (bound to records).
        The predicate function return whether its argument (a single record)
        satisfies the domain.

        This is used to implement ``Model.filtered_domain``.
        """
        raise NotImplementedError

    def optimize(self, model: BaseModel) -> Domain:
        """Perform optimizations of the node given a model.

        It is a pre-processing step to rewrite the domain into a logically
        equivalent domain that is a more canonical representation of the
        predicate. Multiple conditions can be merged together.

        It applies basic optimizations only. Those are transaction-independent;
        they only depend on the model's fields definitions. No model-specific
        override is used, and the resulting domain may be reused in another
        transaction without semantic impact.
        The model's fields are used to validate conditions and apply
        type-dependent optimizations. This optimization level may be useful to
        simplify a domain that is sent to the client-side, thereby reducing its
        payload/complexity.
        """
        return self._optimize(model, OptimizationLevel.BASIC)

    def optimize_dynamic(self, model: BaseModel) -> Domain:
        """Perform optimizations of the node given a model.

        This is an intermediate step between "basic" and "full" optimizations.
        After the basic optimizations, it expands dynamic values like relative
        dates. This enables to check for the actual values in the conditions of
        a domain, for instance.
        """
        return self._optimize(model, OptimizationLevel.DYNAMIC_VALUES)

    def optimize_full(self, model: BaseModel, search_domain: Domain | None = None) -> Domain:
        """Perform optimizations of the node given a model.

        Basic and advanced optimizations are applied.
        Advanced optimizations may rely on model specific overrides
        (search methods of fields, etc.) and the semantic equivalence is only
        guaranteed at the given point in a transaction. We resolve inherited
        and non-stored fields (using their search method) to transform the
        conditions.

        The `search_domain` is the whole domain the user provided for searching.
        """
        if search_domain is not model.env.context.get('search_domain'):
            model = model.with_context(search_domain=search_domain)
        return self._optimize(model, OptimizationLevel.FULL)

    @typing.final
    def _optimize(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Perform optimizations of the node given a model.

        Reach a fixed-point by applying the optimizations for the next level
        on the node until we reach a stable node at the given level.
        """
        domain, previous, count = self, None, 0
        while domain._opt_level < level:
            if (count := count + 1) > MAX_OPTIMIZE_ITERATIONS:
                raise RecursionError("Domain.optimize: too many loops")
            next_level = domain._opt_level.next_level
            previous, domain = domain, domain._optimize_step(model, next_level)
            # set the optimization level if necessary (unlike DomainBool, for instance)
            if domain == previous and domain._opt_level < next_level:
                object.__setattr__(domain, '_opt_level', next_level)  # noqa: PLC2801
        return domain

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Implementation of domain for one level of optimizations."""
        return self

    def _to_sql(self, table: TableSQL) -> SQL:
        """Build the SQL to inject into the query.  The domain should be optimized first."""
        raise NotImplementedError


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


class DomainCondition(Domain):
    """Domain condition on field: (field, operator, value)

    A field (or expression) is compared to a value. The list of supported
    operators are described in CONDITION_OPERATORS.
    """
    __slots__ = ('_field_instance', 'field_expr', 'operator', 'value')
    _field_instance: Field | None  # mutable cached property
    field_expr: str
    operator: str
    value: typing.Any

    def __new__(cls, field_expr: str, operator: str, value):
        """Init a new simple condition (internal init)

        :param field_expr: Field name or field path
        :param operator: A valid operator
        :param value: A value for the comparison
        """
        self = object.__new__(cls)
        object.__setattr__(self, 'field_expr', field_expr)
        object.__setattr__(self, 'operator', operator)
        object.__setattr__(self, 'value', value)
        object.__setattr__(self, '_field_instance', None)
        object.__setattr__(self, '_opt_level', OptimizationLevel.NONE)
        return self

    def checked(self) -> DomainCondition:
        """Validate `self` and return it if correct, otherwise raise an exception."""
        if not isinstance(self.field_expr, str) or not self.field_expr:
            self._raise("Empty field name", error=TypeError)
        operator = self.operator
        if operator not in CONDITION_OPERATORS:
            self._raise("Invalid operator")
        # check already the consistency for domain manipulation
        # these are common mistakes and optimizations, do them here to avoid recreating the domain
        # - NewId is not a value
        # - records are not accepted, use values
        # - Query and Domain values should be using a relational operator
        from odoo.orm.models import BaseModel  # noqa: PLC0415
        value = self.value
        if value is None:
            value = False
        elif isinstance(value, NewId):
            _logger.warning("Domains don't support NewId, use .ids instead, for %r", (self.field_expr, self.operator, self.value))
            operator = 'not in' if operator in NEGATIVE_CONDITION_OPERATORS else 'in'
            value = []
        elif isinstance(value, BaseModel):
            _logger.warning("The domain condition %r should not have a value which is a model", (self.field_expr, self.operator, self.value))
            value = value.ids
        elif isinstance(value, (Domain, Query, SQL)) and operator not in ('any', 'not any', 'any!', 'not any!', 'in', 'not in'):
            # accept SQL object in the right part for simple operators
            # use case: compare 2 fields
            _logger.warning("The domain condition %r should use the 'any' or 'not any' operator.", (self.field_expr, self.operator, self.value))
        if value is not self.value:
            return DomainCondition(self.field_expr, operator, value)
        return self

    def __invert__(self):
        # do it only for simple fields (not expressions)
        # inequalities are handled in _negate()
        if "." not in self.field_expr and (neg_op := _INVERSE_OPERATOR.get(self.operator)):
            return DomainCondition(self.field_expr, neg_op, self.value)
        return super().__invert__()

    def _negate(self, model):
        # inverse of the operators is handled by construction
        # except for inequalities for which we must know the field's type
        if neg_op := _INVERSE_INEQUALITY.get(self.operator):
            # Inverse and add a self "or field is null"
            # when the field does not have a falsy value.
            # Having a falsy value is handled correctly in the SQL generation.
            condition = DomainCondition(self.field_expr, neg_op, self.value)
            if self._field(model).falsy_value is None:
                is_null = DomainCondition(self.field_expr, 'in', OrderedSet([False]))
                condition = is_null | condition
            return condition

        return super()._negate(model)

    def __iter__(self):
        field_expr, operator, value = self.field_expr, self.operator, self.value
        # if the value is a domain or set, change it into a list
        if isinstance(value, (*COLLECTION_TYPES, Domain)):
            value = list(value)
        yield (field_expr, operator, value)

    def __eq__(self, other):
        return self is other or (
            isinstance(other, DomainCondition)
            and self.field_expr == other.field_expr
            and self.operator == other.operator
            # we want stricter equality than this: `OrderedSet([x]) == {x}`
            # to ensure that optimizations always return OrderedSet values
            and self.value.__class__ is other.value.__class__
            and self.value == other.value
        )

    def is_condition(self,
        field_expr: str = '',
        operator: str | tuple[str] = (),
        value: type | tuple[type] = (),
    ) -> bool:
        return (
            not field_expr or self.field_expr == field_expr
        ) and (
            not operator or self.operator in ((operator,) if isinstance(operator, str) else operator)
        ) and (
            not value or isinstance(self.value, value)
        )

    def iter_conditions(self):
        yield self

    def map_conditions(self, function) -> Domain:
        result = function(self)
        assert isinstance(result, Domain), "result of map_conditions is not a Domain"
        return result

    def _raise(self, message: str, *args, error=ValueError) -> typing.NoReturn:
        """Raise an error message for this condition"""
        message += ' in condition (%r, %r, %r)'
        raise error(message % (*args, self.field_expr, self.operator, self.value))

    def _field(self, model: BaseModel) -> Field:
        """Cached Field instance for the expression."""
        field = self._field_instance  # type: ignore[arg-type]
        if field is None or field is not model._fields[field.name]:
            field, _ = self.__get_field(model)
        return field

    def __get_field(self, model: BaseModel) -> tuple[Field, str]:
        """Get the field or raise an exception"""
        field_name, property_name = parse_field_expr(self.field_expr)
        try:
            field = model._fields[field_name]
        except KeyError:
            self._raise("Invalid field %s.%s", model._name, field_name)
        # cache field value, with this hack to bypass immutability
        object.__setattr__(self, '_field_instance', field)
        return field, property_name or ''

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Optimization step.

        Apply some generic optimizations and then dispatch optimizations
        according to the operator and the type of the field.
        Optimize recursively until a fixed point is found.

        - Validate the field.
        - Decompose *paths* into domains using 'any'.
        - If the field is *not stored*, run the search function of the field.
        - Run optimizations.
        - Check the output.
        """
        assert level is self._opt_level.next_level, f"Trying to skip optimization level after {self._opt_level}"

        if level == OptimizationLevel.BASIC:
            # optimize path
            field, property_name = self.__get_field(model)
            if property_name and field.relational:
                sub_domain = DomainCondition(property_name, self.operator, self.value)
                return DomainCondition(field.name, 'any', sub_domain)
        else:
            field = self._field(model)

        if level == OptimizationLevel.FULL:
            # resolve inherited fields
            # inherits implies both Field.delegate=True and Field.bypass_search_access=True
            # so no additional permissions will be added by the 'any' operator below
            if field.inherited:
                assert field.related
                parent_fname = field.related.split('.')[0]
                parent_domain = DomainCondition(self.field_expr, self.operator, self.value)
                return DomainCondition(parent_fname, 'any', parent_domain)

            # handle searchable fields
            if field.search and field.name == self.field_expr:
                if field.type == 'boolean' and isinstance(domain := _optimize_boolean_in_all(self, model), DomainBool):
                    # apply the tautology before trying the search method
                    # this is a basic optimization, but for active flag it is left for later
                    return domain
                domain = self._optimize_field_search_method(model)
                # The domain is optimized so that value data types are comparable.
                # Only simple optimization to avoid endless recursion.
                domain = domain.optimize(model)
                if domain != self:
                    return domain

            if not field.store and not field.compute_sql:
                self._raise("Field has no SQL representation because it is not stored")

        # apply optimizations of the level for operator and type
        optimizations = _OPTIMIZATIONS_FOR[level]
        for opt in optimizations.get(self.operator, ()):
            domain = opt(self, model)
            if domain != self:
                return domain
        for opt in optimizations.get(field.type, ()):
            domain = opt(self, model)
            if domain != self:
                return domain

        # final checks
        if self.operator not in STANDARD_CONDITION_OPERATORS and level == OptimizationLevel.FULL:
            self._raise("Not standard operator left")

        return self

    def _optimize_field_search_method(self, model: BaseModel) -> Domain:
        field = self._field(model)
        operator, value = self.operator, self.value
        env = model.env
        if not env.su:
            if operator not in ('any!', 'not any!'):
                model.check_field_access(field, 'read')
            if field.compute_sudo:
                # run search in sudo because the compute is done in sudo as well
                model = model.sudo()
        if (
            operator in ('any', 'not any', 'any!', 'not any!')
            and field.relational
            and isinstance(value, Domain)
            and not field.related  # related fields handle 'any' properly
            # accept domains which are not context-dependent
            and any(not isinstance(cond.value, (SQL, Query)) for cond in value.iter_conditions())
        ):
            comodel = env[field.comodel_name]
            if field.type in ('many2many', 'one2many'):
                comodel = comodel.with_context(**field.context)
            else:
                comodel = comodel.with_context(active_test=False)
            query = comodel._search(value, bypass_access='!' in operator or field.bypass_search_access)
            value = DomainCondition('id', 'any!', query)

        # use the `Field.search` function
        original_exception = None
        try:
            computed_domain = field.determine_domain(model, operator, value)
        except (NotImplementedError, UserError) as e:
            computed_domain = NotImplemented
            original_exception = e
        else:
            if computed_domain is not NotImplemented:
                return Domain(computed_domain, internal=True)
        # try with the positive operator
        if (
            original_exception is None
            and (inversed_opeator := _INVERSE_OPERATOR.get(operator))
        ):
            try:
                computed_domain = field.determine_domain(model, inversed_opeator, value)
            except (NotImplementedError, UserError):
                pass
            else:
                if computed_domain is not NotImplemented:
                    return ~Domain(computed_domain, internal=True)
        # compatibility for 'any!'
        try:
            if operator in ('any!', 'not any!') and not isinstance(original_exception, AccessError):
                # Not strictly equivalent! If a search is executed, it will be done using sudo.
                computed_domain = DomainCondition(self.field_expr, operator.rstrip('!'), value)
                computed_domain = computed_domain._optimize_field_search_method(model.sudo())
                _logger.warning("Field %s should implement 'any!' operator", field)
                return computed_domain
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        # compatibility for '=' and '!='
        try:
            if operator == 'in':
                return Domain.OR(Domain(field.determine_domain(model, '=', v), internal=True) for v in value)
            if operator == 'not in':
                return Domain.AND(Domain(field.determine_domain(model, '!=', v), internal=True) for v in value)
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        # raise the error
        if isinstance(original_exception, UserError):
            raise original_exception
        raise UserError(env._(
            "Unsupported operator on %(field_label)s %(model_label)s in %(domain)s",
            domain=repr(self),
            field_label=self._field(model).get_description(model.env, ['string'])['string'],
            model_label=f"{model.env['ir.model']._get(model._name).name!r} ({model._name})",
        )) from original_exception

    def _as_predicate(self, records):
        if not records:
            return lambda _: False

        if self._opt_level < OptimizationLevel.DYNAMIC_VALUES:
            return self._optimize(records, OptimizationLevel.DYNAMIC_VALUES)._as_predicate(records)

        operator = self.operator
        if operator in ('child_of', 'parent_of'):
            # TODO have a specific implementation for these
            return self._optimize(records, OptimizationLevel.FULL)._as_predicate(records)

        assert operator in STANDARD_CONDITION_OPERATORS, "Expecting a sub-set of operators"
        field_expr, value = self.field_expr, self.value
        positive_operator = NEGATIVE_CONDITION_OPERATORS.get(operator, operator)

        if isinstance(value, SQL):
            # transform into an Query value
            if positive_operator == operator:
                condition = self
                operator = 'any!'
            else:
                condition = ~self
                operator = 'not any!'
            positive_operator = 'any!'
            field_expr = 'id'
            # similar to a search with [('id', 'in', records.ids), *condition]
            value = records._filtered_access('read')._as_query(ordered=False)
            value.add_where(condition.optimize_full(records, search_domain=Domain('id', 'any!', value))._to_sql(value.table))
            assert isinstance(value, Query)

        if isinstance(value, Query):
            # rebuild a domain with an 'in' values
            if positive_operator not in ('in', 'any', 'any!'):
                self._raise("Cannot filter using Query without the 'any' or 'in' operator")
            if positive_operator != 'in':
                operator = 'in' if positive_operator == operator else 'not in'
                positive_operator = 'in'
            value = set(value.get_result_ids())
            return DomainCondition(field_expr, operator, value)._as_predicate(records)

        field = self._field(records)
        if field_expr == 'display_name':
            # when searching by name, ignore AccessError
            field_expr = 'display_name.no_error'
        elif field_expr == 'id':
            # for new records, compare to their origin
            field_expr = 'id.origin'

        func = field.filter_function(records, field_expr, positive_operator, value)
        return func if positive_operator == operator else lambda rec: not func(rec)

    def _to_sql(self, table: TableSQL) -> SQL:
        field_expr, operator, value = self.field_expr, self.operator, self.value
        assert operator in STANDARD_CONDITION_OPERATORS, \
            f"Invalid operator {operator!r} for SQL in domain term {(field_expr, operator, value)!r}"
        assert self._opt_level >= OptimizationLevel.FULL, \
            f"Must fully optimize before generating the query {(field_expr, operator, value)}"

        model = table._model
        field = self._field(model)
        model.check_field_access(field, 'read')
        return field.condition_to_sql(table, field_expr, operator, value)


ANY_TYPES = (Domain, Query, SQL)


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


@field_type_optimization(['boolean'], OptimizationLevel.FULL)
def _optimize_boolean_in_all(condition, model):
    """b in [True, False]  =>  True"""
    if isinstance(condition.value, COLLECTION_TYPES) and set(condition.value) == {False, True}:
        # tautology is simplified to a boolean
        # note that this optimization removes fields (like active) from the domain
        # so we do this only on FULL level to avoid removing it from sub-domains
        return Domain(condition.operator == 'in')
    return condition


def intersection(sets: list[OrderedSet]) -> OrderedSet:
    """Intersection of a list of OrderedSets"""
    return functools.reduce(operator.and_, sets)


def union(sets: list[OrderedSet]) -> OrderedSet:
    """Union of a list of OrderedSets"""
    return OrderedSet(elem for s in sets for elem in s)

"""Merging of the sibling conditions of the n-ary domains."""

from __future__ import annotations

import typing
from odoo.tools import OrderedSet, partition

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection
    from odoo.orm.models import BaseModel

from ..base import Domain
from ..nary import DomainAnd, DomainNary, DomainOr, intersection, union
from ..condition import DomainCondition
from ..registry import nary_optimization

def nary_condition_optimization(operators: Collection[str], field_types: Collection[str] | None = None):
    """Register an optimization for condition children of an nary domain.

    The function will take a list of domain conditions of the same field and
    returns *optimized* domains.

    This is a adapter function that uses `nary_optimization`.

    NOTE: if you want to merge different operators, register for
    `operator=CONDITION_OPERATORS` and find conditions that you want to merge.
    """
    def register(optimization: Callable[[type[DomainNary], list[DomainCondition], BaseModel], list[Domain]]):
        @nary_optimization
        def optimizer(cls, domains: list[Domain], model):
            # trick: result remains None until an optimization is applied, after
            # which it becomes the optimization of domains[:index]
            result = None
            # when not None, domains[block:index] are all conditions with the same field_expr
            block = None

            domains_iterator = enumerate(domains)
            stop_item = (len(domains), None)
            while True:
                # enumerating domains and adding the stop_item as the sentinel
                # so that the last loop merges the domains and stops the iteration
                index, domain = next(domains_iterator, stop_item)
                matching = isinstance(domain, DomainCondition) and domain.operator in operators

                if block is not None and not (matching and domain.field_expr == domains[block].field_expr):
                    # optimize domains[block:index] if necessary and "flush" them in result
                    if block < index - 1 and (
                        field_types is None or domains[block]._field(model).type in field_types
                    ):
                        if result is None:
                            result = domains[:block]
                        result.extend(optimization(cls, domains[block:index], model))
                    elif result is not None:
                        result.extend(domains[block:index])
                    block = None

                # block is None or (matching and domain.field_expr == domains[block].field_expr)
                if domain is None:
                    break
                if matching:
                    if block is None:
                        block = index
                elif result is not None:
                    result.append(domain)

            # block is None
            return domains if result is None else result

        return optimization

    return register


def _merge_set_conditions(cls: type[DomainNary], conditions):
    """Base function to merge equality conditions.

    Combine the 'in' and 'not in' conditions to a single set of values.

    Examples:

        a in {1} or a in {2}  <=>  a in {1, 2}
        a in {1, 2} and a not in {2, 5}  =>  a in {1}
    """
    assert all(isinstance(cond.value, OrderedSet) for cond in conditions)

    # build the sets for 'in' and 'not in' conditions
    in_sets = [c.value for c in conditions if c.operator == 'in']
    not_in_sets = [c.value for c in conditions if c.operator == 'not in']

    # combine the sets
    field_expr = conditions[0].field_expr
    if cls.OPERATOR == '&':
        if in_sets:
            return [DomainCondition(field_expr, 'in', intersection(in_sets) - union(not_in_sets))]
        else:
            return [DomainCondition(field_expr, 'not in', union(not_in_sets))]
    else:
        if not_in_sets:
            return [DomainCondition(field_expr, 'not in', intersection(not_in_sets) - union(in_sets))]
        else:
            return [DomainCondition(field_expr, 'in', union(in_sets))]


@nary_condition_optimization(operators=('in', 'not in'))
def _optimize_merge_set_conditions_mono_value(cls: type[DomainNary], conditions, model):
    """Merge equality conditions.

    Combine the 'in' and 'not in' conditions to a single set of values.
    Do not touch x2many fields which have a different semantic.

    Examples:

        a in {1} or a in {2}  <=>  a in {1, 2}
        a in {1, 2} and a not in {2, 5}  =>  a in {1}
    """
    field = conditions[0]._field(model)
    if field.type in ('many2many', 'one2many', 'properties'):
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(operators=('in',), field_types=['many2many', 'one2many'])
def _optimize_merge_set_conditions_x2many_in(cls: type[DomainNary], conditions, model):
    """Merge domains of 'in' conditions for x2many fields like for 'any' operator.
    """
    if cls is DomainAnd:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(operators=('not in',), field_types=['many2many', 'one2many'])
def _optimize_merge_set_conditions_x2many_not_in(cls: type[DomainNary], conditions, model):
    """Merge domains of 'not in' conditions for x2many fields like for 'not any' operator.
    """
    if cls is DomainOr:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(['any'], ['many2one', 'one2many', 'many2many'])
@nary_condition_optimization(['any!'], ['many2one', 'one2many', 'many2many'])
def _optimize_merge_any(cls, conditions, model):
    """Merge domains of 'any' conditions for relational fields.

    This will lead to a smaller number of sub-queries which are equivalent.
    Example:

        a any (f = 8) or a any (g = 5)  <=>  a any (f = 8 or g = 5)     (for all fields)
        a any (f = 8) and a any (g = 5)  <=>  a any (f = 8 and g = 5)   (for many2one fields only)
    """
    field = conditions[0]._field(model)
    if field.type != 'many2one' and cls is DomainAnd:
        return conditions
    merge_conditions, other_conditions = partition(lambda c: isinstance(c.value, Domain), conditions)
    if len(merge_conditions) < 2:
        return conditions
    base = merge_conditions[0]
    sub_domain = cls(tuple(c.value for c in merge_conditions))
    return [DomainCondition(base.field_expr, base.operator, sub_domain), *other_conditions]


@nary_condition_optimization(['not any'], ['many2one', 'one2many', 'many2many'])
@nary_condition_optimization(['not any!'], ['many2one', 'one2many', 'many2many'])
def _optimize_merge_not_any(cls, conditions, model):
    """Merge domains of 'not any' conditions for relational fields.

    This will lead to a smaller number of sub-queries which are equivalent.
    Example:

        a not any (f = 1) or a not any (g = 5) => a not any (f = 1 and g = 5)   (for many2one fields only)
        a not any (f = 1) and a not any (g = 5) => a not any (f = 1 or g = 5)   (for all fields)
    """
    field = conditions[0]._field(model)
    if field.type != 'many2one' and cls is DomainOr:
        return conditions
    merge_conditions, other_conditions = partition(lambda c: isinstance(c.value, Domain), conditions)
    if len(merge_conditions) < 2:
        return conditions
    base = merge_conditions[0]
    sub_domain = cls.INVERSE(tuple(c.value for c in merge_conditions))
    return [DomainCondition(base.field_expr, base.operator, sub_domain), *other_conditions]


@nary_optimization
def _optimize_same_conditions(cls, conditions, model):
    """Merge (adjacent) conditions that are the same.

    Quick optimization for some conditions, just compare if we have the same
    condition twice.
    """
    # check if we need to create a new list (this is usually not the case)
    prev = None
    for condition in conditions:
        if prev == condition:
            break
        prev = condition
    else:
        return conditions

    # avoid any function calls, and use the stack semantics for prev comparison
    prev = None
    return [
        condition
        for condition in conditions
        if prev != (prev := condition)
    ]

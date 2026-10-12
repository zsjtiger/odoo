"""Optimizations of the conditions on relational fields: the sub-domains, the hierarchies and the access rules."""

from __future__ import annotations

import functools
import typing
from odoo.exceptions import MissingError
from odoo.tools import SQL, OrderedSet, partition
from odoo.orm.database.query import Query
from odoo.orm.core.utils import COLLECTION_TYPES

if typing.TYPE_CHECKING:
    from odoo.orm.models import BaseModel

from ..classes import ANY_TYPES, Domain, DomainCondition, DomainCustom, _FALSE_DOMAIN, _TRUE_DOMAIN
from ..constants import NEGATIVE_CONDITION_OPERATORS, OptimizationLevel
from ..registry import field_type_optimization, operator_optimization

@operator_optimization(['any', 'not any', 'any!', 'not any!'])
def _optimize_any_domain(condition, model):
    """Make sure the value is an optimized domain (or Query or SQL)"""
    value = condition.value
    if isinstance(value, ANY_TYPES) and not isinstance(value, Domain):
        if condition.operator in ('any', 'not any'):
            # update operator to 'any!'
            return DomainCondition(condition.field_expr, condition.operator + '!', condition.value)
        return condition
    domain = Domain(value)
    field = condition._field(model)
    if field.name == 'id':
        # id ANY domain  <=>  domain
        # id NOT ANY domain  <=>  ~domain
        return domain if condition.operator in ('any', 'any!') else ~domain
    if value is domain:
        # avoid recreating the same condition
        return condition
    return DomainCondition(condition.field_expr, condition.operator, domain)


def _optimize_any_domain_at_level(level: OptimizationLevel, condition, model):
    domain = condition.value
    if not isinstance(domain, Domain):
        return condition

    field = condition._field(model)
    if not field.relational:
        condition._raise("Cannot use 'any' with non-relational fields")

    try:
        comodel = model.env[field.comodel_name]
    except KeyError:
        condition._raise("Cannot determine the comodel relation")

    if field.type in ('many2many', 'one2many'):
        comodel = comodel.with_context(**field.context)
    else:
        comodel = comodel.with_context(active_test=False)

    if isinstance(search_domain := model.env.context.get('search_domain'), Domain):
        # model with search_domain like (field, 'any', comodel_domain)
        # => comodel with comodel_domain
        # a plain (field, 'in', ids) condition on the same field is just as
        # informative: it directly constrains the comodel's own 'id'.
        # '=' is not checked: it's always normalized to 'in' by the time a
        # domain is fully optimized (see _operator_equal_as_in), so it can
        # never survive here.
        comodel_domain = Domain.OR(
            c.value if isinstance(c.value, Domain) else DomainCondition('id', c.operator, c.value)
            for c in search_domain.iter_conditions()
            if c.is_condition(condition.field_expr)
            and (isinstance(c.value, Domain) or c.operator == 'in')
        )
        if comodel_domain.is_false() and not search_domain.is_false():
            # we don't know the constraining condition
            if field.type == 'many2one' and (field.store or field.compute_sql) and level > OptimizationLevel.BASIC:
                # restrict using the whole domain
                def restricted_domain_sql(table):
                    sub_query = model.sudo()._search(search_domain, active_test=False, bypass_access=True)
                    return SQL("%s IN %s", table.id, sub_query.subselect(sub_query.table[field.name]))
                comodel_domain = Domain.custom(to_sql=restricted_domain_sql)
            else:
                # in general case, accept all
                comodel_domain = Domain.TRUE
        comodel = comodel.with_context(search_domain=comodel_domain)

    domain = domain._optimize(comodel, level)
    # const if the domain is empty, the result is a constant
    # if the domain is True, we keep it as is
    if domain.is_false():
        return _FALSE_DOMAIN if condition.operator in ('any', 'any!') else _TRUE_DOMAIN
    if domain is condition.value:
        # avoid recreating the same condition
        return condition
    return DomainCondition(condition.field_expr, condition.operator, domain)


[
    operator_optimization(('any', 'not any', 'any!', 'not any!'), level)(functools.partial(_optimize_any_domain_at_level, level))
    for level in OptimizationLevel
    if level > OptimizationLevel.NONE
]


@field_type_optimization(['many2one', 'one2many', 'many2many'])
def _optimize_relational_name_search(condition, model):
    """Search relational using `display_name`.

    When a relational field is compared to a string, we actually want to make
    a condition on the `display_name` field.
    Negative conditions are translated into a "not any" for consistency.
    """
    operator = condition.operator
    value = condition.value
    positive_operator = NEGATIVE_CONDITION_OPERATORS.get(operator, operator)
    any_operator = 'any' if positive_operator == operator else 'not any'
    # Handle like operator
    if operator.endswith('like'):
        return DomainCondition(
            condition.field_expr,
            any_operator,
            DomainCondition('display_name', positive_operator, value),
        )
    # Handle inequality as not supported
    if operator[0] in ('<', '>') and isinstance(value, str):
        condition._raise("Inequality not supported for relational field using a string", error=TypeError)
    # Handle equality with str values
    if positive_operator != 'in' or not isinstance(value, COLLECTION_TYPES):
        return condition
    str_values, other_values = partition(lambda v: isinstance(v, str), value)
    if not str_values:
        return condition
    domain = DomainCondition(
        condition.field_expr,
        any_operator,
        DomainCondition('display_name', positive_operator, str_values),
    )
    if other_values:
        if positive_operator == operator:
            domain |= DomainCondition(condition.field_expr, operator, other_values)
        else:
            domain &= DomainCondition(condition.field_expr, operator, other_values)
    return domain


@operator_optimization(['parent_of', 'child_of'], OptimizationLevel.FULL)
def _operator_hierarchy(condition, model):
    """Transform a hierarchy operator into a simpler domain.

    ### Semantic of hierarchical operator: `(field, operator, value)`

    `field` is either 'id' to indicate to use the default parent relation (`_parent_name`)
    or it is a field where the comodel is the same as the model.
    The value is used to search a set of `related_records`. We start from the given value,
    which can be ids, a name (for searching by name), etc. Then we follow up the relation;
    forward in case of `parent_of` and backward in case of `child_of`.
    The resulting domain will have 'id' if the field is 'id' or a many2one.

    In the case where the comodel is not the same as the model, the result is equivalent to
    `('field', 'any', ('id', operator, value))`
    """
    if condition.operator == 'parent_of':
        hierarchy = _operator_parent_of_domain
    else:
        hierarchy = _operator_child_of_domain
    value = condition.value
    if value is False:
        return _FALSE_DOMAIN
    # Get:
    # - field: used in the resulting domain)
    # - parent (str | None): field name to find parent in the hierarchy
    # - comodel_sudo: used to resolve the hierarchy
    # - comodel: used to search for ids based on the value
    field = condition._field(model)
    if field.type == 'many2one':
        comodel = model.env[field.comodel_name].with_context(active_test=False)
    elif field.type in ('one2many', 'many2many'):
        comodel = model.env[field.comodel_name].with_context(**field.context)
    elif field.name == 'id':
        comodel = model
    else:
        condition._raise(f"Cannot execute {condition.operator} for {field}, works only for relational fields")
    comodel_sudo = comodel.sudo().with_context(active_test=False)
    parent = comodel._parent_name
    if comodel._name == model._name:
        if condition.field_expr != 'id':
            parent = condition.field_expr
        if field.type == 'many2one':
            field = model._fields['id']
    # Get the initial ids and bind them to comodel_sudo before resolving the hierarchy
    if isinstance(value, (int, str)):
        value = [value]
    elif not isinstance(value, COLLECTION_TYPES):
        condition._raise(f"Value of type {type(value)} is not supported")
    coids, other_values = partition(lambda v: isinstance(v, int), value)
    search_domain = _FALSE_DOMAIN
    if field.type == 'many2many':
        # always search for many2many
        search_domain |= DomainCondition('id', 'in', coids)
        coids = []
    if other_values:
        # search for strings
        search_domain |= Domain.OR(
            Domain('display_name', 'ilike', v)
            for v in other_values
        )
    coids += comodel.search(search_domain, order='id').ids
    if not coids:
        return _FALSE_DOMAIN
    result = hierarchy(comodel_sudo.browse(coids), parent)
    # Format the resulting domain
    if isinstance(result, Domain):
        if field.name == 'id':
            return result
        return DomainCondition(field.name, 'any!', result)
    return DomainCondition(field.name, 'in', result)


def _operator_child_of_domain(comodel: BaseModel, parent):
    """Return a set of ids or a domain to find all children of given model"""
    if comodel._parent_store and parent == comodel._parent_name:
        try:
            paths = comodel.mapped('parent_path')
        except MissingError:
            paths = comodel.exists().mapped('parent_path')
        domain = Domain.OR(
            DomainCondition('parent_path', '=like', path + '%')  # type: ignore
            for path in paths
        )
        return domain
    else:
        # recursively retrieve all children nodes with sudo(); the
        # filtering of forbidden records is done by the rest of the
        # domain
        child_ids: OrderedSet[int] = OrderedSet()
        while comodel:
            child_ids.update(comodel._ids)
            # same as searching with the condition and bypassing all rules and overrides
            query = Query(comodel)
            query.add_where(DomainCondition(parent, 'in', comodel._ids).optimize_full(comodel)._to_sql(query.table))
            comodel = comodel.browse(OrderedSet(query.get_result_ids()) - child_ids)
    return child_ids


def _operator_parent_of_domain(comodel: BaseModel, parent):
    """Return a set of ids or a domain to find all parents of given model"""
    parent_ids: OrderedSet[int]
    if comodel._parent_store and parent == comodel._parent_name:
        try:
            paths = comodel.mapped('parent_path')
        except MissingError:
            paths = comodel.exists().mapped('parent_path')
        parent_ids = OrderedSet(
            int(label)
            for path in paths
            for label in path.split('/')[:-1]
        )
    else:
        # recursively retrieve all parent nodes with sudo() to avoid
        # access rights errors; the filtering of forbidden records is
        # done by the rest of the domain
        parent_ids = OrderedSet()
        try:
            comodel.mapped(parent)
        except MissingError:
            comodel = comodel.exists()
        while comodel:
            parent_ids.update(comodel._ids)
            comodel = comodel[parent].filtered(lambda p: p.id not in parent_ids)
    return parent_ids


@operator_optimization(['access'], level=OptimizationLevel.DYNAMIC_VALUES)
def _operator_access_rule_domain(condition, model):
    field = condition._field(model)
    if condition.field_expr != field.name:
        condition._raise("The 'access' operator does not work for properties")

    if field.name == 'id':
        comodel = model
    elif field.type == 'many2one' and field.comodel_name:
        comodel = model.env[field.comodel_name]
    else:
        condition._raise("The 'access' operator works only for many2one and 'id' fields")
        assert False, "no return above"  # for pylint

    operation = condition.value
    if operation not in ('read', 'write', 'create', 'unlink'):
        condition._raise("Invalid value for 'access' operator")

    comodel = comodel.sudo(False)
    access_domain = comodel._access_domain(operation)
    if access_domain.is_false():
        # no access to the comodel for any record
        return Domain.FALSE
    if access_domain.is_true() or comodel.env.su:
        # access to all or edge-case for super user
        return DomainCondition(field.name, '!=', False)

    def filtered_access(record):
        if field.name == 'id':
            return record.sudo(False).has_access(operation)
        return (
            record.has_access('read')
            and (corecord := field.__get__(record.sudo()))
            and corecord.sudo(False).has_access(operation)
        )

    def optimize_sql(custom, model):
        return DomainCondition(field.name, 'any!', access_domain)

    return DomainCustom(filtered=filtered_access, optimize_func=optimize_sql)


@operator_optimization(['any', 'not any'], level=OptimizationLevel.FULL)
def _optimize_any_with_rights(condition, model):
    if model.env.su or condition._field(model).bypass_search_access:
        return DomainCondition(condition.field_expr, condition.operator + '!', condition.value)
    return condition


@field_type_optimization(['many2one'], level=OptimizationLevel.FULL)
def _optimize_m2o_bypass_comodel_id_lookup(condition, model):
    """Avoid comodel's subquery, if it can be compared with the field directly"""
    operator = condition.operator
    if (
        operator in ('any!', 'not any!')
        and isinstance(subdomain := condition.value, DomainCondition)
        and subdomain.field_expr == 'id'
        and (suboperator := subdomain.operator) in ('in', 'not in', 'any!', 'not any!')
    ):
        # We are bypassing permissions, we can transform:
        #  a ANY (id IN X)  =>  a IN (X - {False})
        #  a ANY (id NOT IN X)  =>  a NOT IN (X | {False})
        #  a ANY (id ANY X)  =>  a ANY X
        #  a ANY (id NOT ANY X)  =>  a != False AND a NOT ANY X
        #  a NOT ANY (id IN X)  =>  a NOT IN (X - {False})
        #  a NOT ANY (id NOT IN X)  =>  a IN (X | {False})
        #  a NOT ANY (id ANY X)  =>  a NOT ANY X
        #  a NOT ANY (id NOT ANY X)  =>  a = False OR a ANY X
        val = subdomain.value
        match suboperator:
            case 'in':
                domain = DomainCondition(condition.field_expr, 'in', val - {False})
            case 'not in':
                domain = DomainCondition(condition.field_expr, 'not in', val | {False})
            case 'any!':
                domain = DomainCondition(condition.field_expr, 'any!', val)
            case 'not any!':
                domain = DomainCondition(condition.field_expr, '!=', False) \
                    & DomainCondition(condition.field_expr, 'not any!', val)
        if operator == 'not any!':
            domain = ~domain
        return domain
    return condition


@field_type_optimization(['one2many', 'many2many'], level=OptimizationLevel.FULL)
def _optimize_x2m_in_operator(condition, model):
    """For x2m fields, we always will generate a query so we can express it as
    the "any!" operator directly.
    """
    if condition.operator not in ('in', 'not in'):
        return condition
    field_expr = condition.field_expr
    ids = condition.value
    # rewrite condition (field_expr, 'in', ids), then negate in the case 'not in'
    domain = Domain.FALSE
    comodel = model.env[condition._field(model).comodel_name]
    if False in ids:
        # x2m in {False, ...} => x2m not any! (Domain.TRUE) or x2m in {...}
        domain |= Domain(field_expr, 'not any!', Query(comodel))
        ids = ids - {False}
    if ids:
        # x2m in ids => x2m any! (ids_as_query)
        domain |= Domain(field_expr, 'any!', comodel.browse(ids)._as_query(ordered=False))
    return domain if condition.operator == 'in' else ~domain

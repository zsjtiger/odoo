"""Queries on the fields: the SQL and the Python predicates of the conditions on the fields."""

from __future__ import annotations

import re
import typing
from collections.abc import Set as AbstractSet
from odoo.tools import SQL
from odoo.orm.core.domains import Domain
from odoo.orm.database.query import Query
from odoo.orm.core.utils import COLLECTION_TYPES, SQL_OPERATORS, SUPERUSER_ID, parse_field_expr

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from odoo.orm.database.query import FieldSQL, TableSQL
    from odoo.orm.core.types import BaseModel

from .base import PYTHON_INEQUALITY_OPERATOR, determine

def to_sql(self, table: TableSQL) -> SQL:
    """ Return an :class:`SQL` object that represents the value of the given
    field from the given table alias.

    The query object is necessary for fields that need to add tables to the query.
    """
    model = table._model
    model.check_field_access(self, 'read')
    if self.compute_sql:
        if self.compute_sudo:
            model = model.sudo()
            table = table._with_model(model)
        sql_field = determine(self.compute_sql, model, table)
        assert isinstance(sql_field, SQL), f"{self} invalid return of compute_sql"
        return sql_field
    if not self.store or not self.column_type:
        if self.related and not self.store:
            # traverse_related
            return self._compute_sql_related(model, table)
        raise ValueError(f"Cannot convert {self} to SQL because it is not stored")
    sql_field = SQL.identifier(table._alias, self.name, to_flush=self)
    if self.company_dependent:
        company_id = model.env.context.get('sql_company_id')
        if isinstance(company_id, SQL):
            fallback = model.env['ir.default'].sudo()._search([
                ('field_id', '=', model.env['ir.model.fields']._get(self.model_name, self.name).id),
                ('user_id', 'in', (False, SUPERUSER_ID)),
                Domain.custom(to_sql=lambda table: SQL("(%s IS NULL OR %s = %s)", table.company_id, table.company_id, company_id)),
                ('condition', '=', False),
            ], order="user_id.id, company_id.id, id", limit=1).subselect(SQL('json_value'))
        else:
            company_id = str(model.env.company.id)
            fallback = self.get_company_dependent_fallback(model)
            fallback = self.convert_to_column(self.convert_to_write(fallback, model), model)
        # in _read_group_orderby the result of field to sql will be mogrified and split to
        # e.g SQL('COALESCE(%s->%s') and SQL('to_jsonb(%s))::boolean') as 2 orderby values
        # and concatenated by SQL(',') in the final result, which works in an unexpected way
        sql_field = SQL(
            'COALESCE(%(column)s->(%(company_id)s::"varchar"),to_jsonb(%(fallback)s::%(column_type)s))',
            column=sql_field,
            company_id=company_id,
            fallback=fallback,
            column_type=self.sql_column_type,
        )
        if self.type in ('boolean', 'integer', 'float', 'monetary'):
            return SQL('(%s)::%s', sql_field, self.sql_column_type)
        # here the specified value for a company might be NULL e.g. '{"1": null}'::jsonb
        # the result of current sql_field might be 'null'::jsonb
        # ('null'::jsonb)::text == 'null'
        # ('null'::jsonb->>0)::text IS NULL
        return SQL('(%s->>0)::%s', sql_field, self.sql_column_type)

    return sql_field


def property_to_sql(self, field_sql: FieldSQL, property_name: str) -> SQL:
    """ Return an :class:`SQL` object that represents the value of the given
    expression from the given table alias.

    The query object is necessary for fields that need to add tables to the query.
    """
    raise ValueError(f"Invalid field property {property_name!r} on {self}")


def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
    """ Return an :class:`SQL` object that represents the domain condition
    given by the triple ``(field_expr, operator, value)`` with the given
    table alias, and in the context of the given query.

    This method should use the model to resolve the SQL and check access
    of the field.
    """
    sql_expr = self._condition_to_sql(table, field_expr, operator, value)
    if self.company_dependent:
        sql_expr = self._condition_to_sql_company(table, sql_expr, field_expr, operator, value)
    return sql_expr


def _condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
    model = table._model
    fname, property_name = parse_field_expr(field_expr)
    sql_field = table[fname]

    if not property_name:
        def _value_to_column(v):
            return self.convert_to_column(v, model, validate=False)
    else:
        # reading a property, keep value as-is
        def _value_to_column(v):
            return v
        sql_field = sql_field[property_name]

    # support for SQL value
    if operator in SQL_OPERATORS and isinstance(value, SQL):
        condition = (field_expr, operator, value)
        raise TypeError(f"Unexpected SQL in condition {condition}, use Domain.custom() instead")

    # nullability
    can_be_null = self not in model.env.registry.not_null_fields

    # operator: in (equality)
    if operator in ('in', 'not in'):
        assert isinstance(value, COLLECTION_TYPES), \
            f"condition_to_sql() 'in' operator expects a collection, not a {value!r}"
        params = tuple(_value_to_column(v) for v in value if v is not False and v is not None)
        null_in_condition = len(params) < len(value)
        # if we have a value treated as null
        if (null_value := self.falsy_value) is not None:
            null_value = _value_to_column(null_value)
            if null_value in params:
                null_in_condition = True
            elif null_in_condition:
                params = (*params, null_value)

        sql = None
        if params:
            sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], params)

        if (operator == 'in') == null_in_condition:
            # field in {val, False} => field IN vals OR field IS NULL
            # field not in {val} => field NOT IN vals OR field IS NULL
            if not can_be_null:
                return sql or SQL("FALSE")
            sql_null = SQL("%s IS NULL", sql_field)
            return SQL("(%s OR %s)", sql, sql_null) if sql else sql_null

        elif operator == 'not in' and null_in_condition and not sql:
            # if we have a base query, null values are already exluded
            return SQL("%s IS NOT NULL", sql_field) if can_be_null else SQL("TRUE")

        assert sql, f"Missing sql query for {operator} {value!r}"
        return sql

    # operator: like
    if operator.endswith('like'):
        # cast value to text for any like comparison
        sql_left = sql_field if self.is_text else SQL("%s::text", sql_field)

        # add wildcard and unaccent depending on the operator
        need_wildcard = '=' not in operator
        if need_wildcard:
            sql_value = SQL("%s", f"%{value}%")
        else:
            sql_value = SQL("%s", str(value))
        if operator.endswith('ilike'):
            sql_left = model.env.registry.unaccent(sql_left)
            sql_value = model.env.registry.unaccent(sql_value)

        sql = SQL("%s%s%s", sql_left, SQL_OPERATORS[operator], sql_value)
        if operator in Domain.NEGATIVE_OPERATORS and can_be_null:
            sql = SQL("(%s OR %s IS NULL)", sql, sql_field)
        return sql

    # operator: inequality
    if operator in ('>', '<', '>=', '<='):
        accept_null_value = False
        if (null_value := self.falsy_value) is not None:
            value = self.convert_to_cache(value, model) or null_value
            accept_null_value = can_be_null and (
                null_value < value if operator == '<' else
                null_value > value if operator == '>' else
                null_value <= value if operator == '<=' else
                null_value >= value  # operator == '>='
            )
        sql_value = SQL("%s", _value_to_column(value))

        sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], sql_value)
        if accept_null_value:
            sql = SQL("(%s OR %s IS NULL)", sql, sql_field)
        return sql

    # operator: any
    # Note: relational operators overwrite this function for a more specific
    # behaviour, here we check just the field against the subselect.
    # Example usage: ('id', 'any!', Query | SQL)
    if operator in ('any!', 'not any!'):
        if isinstance(value, Query):
            subselect = value.subselect()
        elif isinstance(value, SQL):
            subselect = SQL("(%s)", value)
        else:
            raise TypeError(f"condition_to_sql() operator 'any!' accepts SQL or Query, got {value}")
        sql_operator = SQL_OPERATORS["in" if operator == "any!" else "not in"]
        return SQL("%s%s%s", sql_field, sql_operator, subselect)

    raise NotImplementedError(f"Invalid operator {operator!r} for SQL in domain term {(field_expr, operator, value)!r}")


def _condition_to_sql_company(self, table: TableSQL, sql_expr: SQL, field_expr: str, operator: str, value) -> SQL:
    """ Add a not null condition on the field for company-dependent fields to use an existing index for better performance."""
    model = table._model
    if (
        self.company_dependent
        and self.index == 'btree_not_null'
        and not (self.type in ('datetime', 'date') and field_expr != self.name)  # READ_GROUP_NUMBER_GRANULARITY is not supported
        and model.env['ir.default']._evaluate_condition_with_fallback(model._name, field_expr, operator, value) is False
    ):
        return SQL('(%s IS NOT NULL AND %s)', SQL.identifier(table._alias, self.name), sql_expr)
    return sql_expr


def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
    """ Given some field expression (what you find in domain conditions),
    return a function that returns the corresponding expression for a record::

        field = record._fields['create_date']
        get_value = field.expression_getter('create_date.month_number')
        month_number = get_value(record)
    """
    if field_expr == self.name:
        return self.__get__
    raise ValueError(f"Expression not supported on {self}: {field_expr!r}")


def filter_function[M: BaseModel](self, records: M, field_expr: str, operator: str, value) -> Callable[[M], M]:
    assert operator not in Domain.NEGATIVE_OPERATORS, "only positive operators are implemented"
    getter = self.expression_getter(field_expr)
    # assert not isinstance(value, (SQL, Query))

    # -------------------------------------------------
    # operator: in (equality)
    if operator == 'in':
        assert isinstance(value, COLLECTION_TYPES) and value, \
            f"filter_function() 'in' operator expects a collection, not a {type(value)}"
        if not isinstance(value, AbstractSet):
            value = set(value)
        if False in value or self.falsy_value in value:
            if len(value) == 1:
                return lambda rec: not getter(rec)
            return lambda rec: (val := getter(rec)) in value or not val
        return lambda rec: getter(rec) in value

    # -------------------------------------------------
    # operator: like
    if operator.endswith('like'):
        # we may get a value which is not a string
        if operator.endswith('ilike'):
            # ilike uses unaccent and lower-case comparison
            unaccent_python = records.env.registry.unaccent_python

            def unaccent(x):
                return unaccent_python(str(x).lower()) if x else ''
        else:
            def unaccent(x):
                return str(x) if x else ''

        # build a regex that matches the SQL-like expression
        # note that '\' is used for escaping in SQL
        def build_like_regex(value: str, exact: bool):
            yield '^' if exact else '.*'
            escaped = False
            for char in value:
                if escaped:
                    escaped = False
                    yield re.escape(char)
                elif char == '\\':
                    escaped = True
                elif char == '%':
                    yield '.*'
                elif char == '_':
                    yield '.'
                else:
                    yield re.escape(char)
            if exact:
                yield '$'
            # no need to match r'.*' in else because we only use .match()

        like_regex = re.compile("".join(build_like_regex(unaccent(value), "=" in operator)), flags=re.DOTALL)
        return lambda rec: like_regex.match(unaccent(getter(rec)))

    # -------------------------------------------------
    # operator: inequality
    if pyop := PYTHON_INEQUALITY_OPERATOR.get(operator):
        can_be_null = False
        if (null_value := self.falsy_value) is not None:
            value = value or null_value
            can_be_null = (
                null_value < value if operator == '<' else
                null_value > value if operator == '>' else
                null_value <= value if operator == '<=' else
                null_value >= value  # operator == '>='
            )

        def check_inequality(rec):
            rec_value = getter(rec)
            try:
                if rec_value is False or rec_value is None:
                    return can_be_null
                return pyop(rec_value, value)
            except (ValueError, TypeError):
                # ignoring error, type mismatch
                return False
        return check_inequality

    # -------------------------------------------------
    raise NotImplementedError(f"Invalid simple operator {operator!r}")


def determine_inverse(self, records):
    """ Given the value of ``self`` on ``records``, inverse the computation. """
    determine(self.inverse, records)


def determine_domain(self, records: BaseModel, operator: str, value) -> typing.Any:
    """ Return a domain representing a condition on ``self``. """
    return determine(self.search, records, operator, value)


def determine_group_expand(self, records, values, domain):
    """ Return a domain representing a condition on ``self``. """
    return determine(self.group_expand, records, values, domain)

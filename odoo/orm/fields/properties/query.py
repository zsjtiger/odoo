"""Queries on the properties: the SQL and the Python predicates of the conditions on the properties."""

from __future__ import annotations

import json
import typing
from odoo.exceptions import UserError
from odoo.tools import SQL, sql
from odoo.orm.core.domains import Domain
from odoo.orm.fields.temporal import BaseDate
from odoo.orm.models import BaseModel
from odoo.orm.database.query import Query
from odoo.orm.core.utils import COLLECTION_TYPES, SQL_OPERATORS, parse_field_expr

if typing.TYPE_CHECKING:
    from odoo.orm.database.query import FieldSQL, TableSQL

from .base import Properties, check_property_field_value_name

def expression_getter(self, field_expr):
    _fname, property_name = parse_field_expr(field_expr)
    if not property_name:
        raise ValueError(f"Missing property name for {self}")

    def get_property(record):
        property_value = self.__get__(record)
        value = property_value.get(property_name)
        if value:
            return value
        # find definition to check the type
        for definition in self._get_properties_definition(record) or ():
            if definition.get('name') == property_name:
                break
        else:
            # definition not found
            return value or False

        if not value and definition['type'] in ('many2one', 'many2many'):
            return record.env.get(definition.get('comodel'))
        return value

    return get_property


def filter_function(self, records, field_expr, operator, value):
    getter = self.expression_getter(field_expr)
    domain = None
    if operator == 'any' or isinstance(value, Domain):
        domain = Domain(value).optimize(records)
    elif operator == 'in' and isinstance(value, COLLECTION_TYPES) and isinstance(getter(records.browse()), BaseModel):
        domain = Domain('id', 'in', value).optimize(records)
    if domain is not None:
        return lambda rec: getter(rec).filtered_domain(domain)
    return super(Properties, self).filter_function(records, field_expr, operator, value)


def property_to_sql_raw(self, field_sql: SQL, property_name: str) -> SQL:
    check_property_field_value_name(property_name)
    return SQL("(%s -> %s)", field_sql, property_name)


def property_to_sql(self, field_sql: FieldSQL, property_name: str) -> SQL:
    # NOTE: This function misbehaves for groupby so that the query rowcount
    # is duplicated when accessing multi-valued properties (like tags).
    sql_property = self.property_to_sql_raw(field_sql, property_name)
    fname = self.name
    table = field_sql._table
    model = table._model
    definition = model.get_property_definition(f"{fname}.{property_name}")
    property_type = definition.get('type')

    # JOIN on the JSON array
    if property_type in ('tags', 'many2many'):
        property_alias = table._make_alias(f'{fname}_{property_name}')
        sql_property = SQL(
            """ CASE
                    WHEN jsonb_typeof(%(property)s) = 'array'
                    THEN %(property)s
                    ELSE '[]'::jsonb
                 END """,
            property=sql_property,
        )
        if property_type == 'tags':
            # ignore invalid tags
            tags = [tag[0] for tag in definition.get('tags') or []]
            # `->>0 : convert "JSON string" into string
            condition = SQL(
                "%s->>0 = ANY(%s::text[])",
                property_alias, tags,
            )
        else:
            comodel = model.env.get(definition.get('comodel'))
            if comodel is None or comodel._transient or comodel._abstract:
                raise UserError(model.env._(
                    "You cannot use “%(property_name)s” because the linked “%(model_name)s” model doesn't exist or is invalid",
                    property_name=definition.get('string', property_name), model_name=definition.get('comodel'),
                ))

            # check the existences of the many2many
            condition = SQL(
                "%s::int IN (SELECT id FROM %s)",
                property_alias, SQL.identifier(comodel._table),
            )

        table._query.add_join(
            "LEFT JOIN",
            property_alias,
            SQL("jsonb_array_elements(%s)", sql_property),
            condition,
        )

        return property_alias

    elif property_type == 'selection':
        options = [option[0] for option in definition.get('selection') or ()]

        # check the existence of the option
        property_alias = table._make_alias(f'{fname}_{property_name}')
        table._query.add_join(
            "LEFT JOIN",
            property_alias,
            SQL("(SELECT unnest(%s::text[]) %s)", options, property_alias),
            SQL("%s->>0 = %s", sql_property, property_alias),
        )

        return property_alias

    elif property_type == 'many2one':
        comodel = model.env.get(definition.get('comodel'))
        if comodel is None or comodel._transient or comodel._abstract:
            raise UserError(model.env._(
                "You cannot use “%(property_name)s” because the linked “%(model_name)s” model doesn't exist or is invalid",
                property_name=definition.get('string', property_name), model_name=definition.get('comodel'),
            ))

        return SQL(
            """ CASE
                    WHEN jsonb_typeof(%(property)s) = 'number'
                     AND (%(property)s)::int IN %(table)s
                    THEN %(property)s
                    ELSE NULL
                 END """,
            property=sql_property,
            table=Query(comodel).subselect(),
        )

    elif property_type == 'date':
        return SQLWithProperty(
            """ CASE
                    WHEN jsonb_typeof(%(property)s) = 'string'
                    THEN (%(property)s->>0)::DATE
                    ELSE NULL
                 END """,
            property=sql_property,
            property_func=lambda self, name: BaseDate._generic_property_to_sql('date', self, name, model),
        )

    elif property_type == 'datetime':
        return SQLWithProperty(
            """ CASE
                    WHEN jsonb_typeof(%(property)s) = 'string'
                    THEN to_timestamp(%(property)s->>0, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE NULL
                 END """,
            property=sql_property,
            property_func=lambda self, name: BaseDate._generic_property_to_sql('datetime', self, name, model),
        )

    elif property_type == 'html':
        raise UserError(model.env._('Grouping by HTML properties is not supported.'))

    # if the key is not present in the dict, fallback to false instead of none
    return SQL("COALESCE(%s, 'false')", sql_property)


def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
    fname, property_name = parse_field_expr(field_expr)
    if not property_name:
        raise ValueError(f"Missing property name for {self}")
    raw_sql_field = table[fname]
    sql_left = self.property_to_sql_raw(raw_sql_field, property_name)

    if operator in ('in', 'not in'):
        assert isinstance(value, COLLECTION_TYPES)
        if len(value) == 1 and any(v is True for v in value):
            # inverse the condition
            check_null_op_false = "!=" if operator == 'in' else "="
            value = []
            operator = 'in' if operator == 'not in' else 'not in'
        elif False in value:
            check_null_op_false = "=" if operator == 'in' else "!="
            value = [v for v in value if v]
        else:
            value = list(value)
            check_null_op_false = None

        sqls = []
        if check_null_op_false:
            sqls.append(SQL(
                "%s%s'%s'",
                sql_left,
                SQL_OPERATORS[check_null_op_false],
                False,
            ))
            if check_null_op_false == '=':
                # check null value too
                sqls.extend((
                    SQL("%s IS NULL", raw_sql_field),
                    SQL("NOT (%s ? %s)", raw_sql_field, property_name),
                ))
        # left can be an array or a single value!
        # Even if we use the '=' operator, we must check the list subset.
        # There is an unsupported edge-case where left is a list and we
        # have multiple values.
        if len(value) == 1:
            # check single value equality
            sql_operator = SQL_OPERATORS['=' if operator == 'in' else '!=']
            sql_right = SQL("%s", json.dumps(value[0]))
            sqls.append(SQL("%s%s%s", sql_left, sql_operator, sql_right))
        if value:
            sql_not = SQL('NOT ') if operator == 'not in' else SQL()
            # hackish operator to search values
            if len(value) > 1:
                # left <@ value_list -- single left value in value_list
                # (here we suppose left is a single value)
                sql_operator = SQL(" <@ ")
            else:
                # left @> value -- value_list in left
                sql_operator = SQL(" @> ")
            sql_right = SQL("%s", json.dumps(value))
            sqls.append(SQL(
                "%s%s%s%s",
                sql_not, sql_left, sql_operator, sql_right,
            ))
        assert sqls, "No SQL generated for property"
        if len(sqls) == 1:
            return sqls[0]
        combine_sql = SQL(" OR ") if operator == 'in' else SQL(" AND ")
        return SQL("(%s)", combine_sql.join(sqls))

    unaccent = lambda x: x  # noqa: E731
    if operator.endswith('like'):
        if operator.endswith('ilike'):
            unaccent = table._model.env.registry.unaccent
        if '=' in operator:
            value = str(value)
        else:
            value = f'%{value}%'

    try:
        sql_operator = SQL_OPERATORS[operator]
    except KeyError:
        raise ValueError(f"Invalid operator {operator} for Properties")

    if isinstance(value, str):
        sql_left = SQL("(%s ->> %s)", raw_sql_field, property_name)  # JSONified value
        sql_right = SQL("%s", value)
        sql = SQL(
            "%s%s%s",
            unaccent(sql_left), sql_operator, unaccent(sql_right),
        )
        if operator in Domain.NEGATIVE_OPERATORS:
            sql = SQL("(%s OR %s IS NULL)", sql, sql_left)
        return sql

    sql_right = SQL("%s", json.dumps(value))
    return SQL(
        "%s%s%s",
        unaccent(sql_left), sql_operator, unaccent(sql_right),
    )


class SQLWithProperty(sql.LiteralSQL):
    def __init__(self, code, /, *args, property_func, **kw):
        super().__init__(code, *args, **kw)
        self._property = property_func

    def __getitem__(self, name):
        return self._property(self, name)

    __getattr__ = __getitem__

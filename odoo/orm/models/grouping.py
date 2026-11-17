# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Read group: the grouping sets, the SQL of the groups and the aggregates of the records."""

from __future__ import annotations

import itertools
import re
import typing
from collections import defaultdict
from operator import call

import psycopg2.extensions

from odoo.tools import (
    get_lang, unique,
    SQL,
)


from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import (
    parse_field_expr,
    SQL_OPERATORS,
)

if typing.TYPE_CHECKING:
    from collections.abc import Sequence
    from odoo.orm.core.types import DomainType, ModelType


regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")

from odoo.orm.models import BaseModel, READ_GROUP_AGGREGATE, itemgetter_tuple, parse_read_group_spec


def _read_grouping_sets(self, domain: DomainType, grouping_sets: Sequence[Sequence[str]], aggregates: Sequence[str]=(), order: str | None=None) -> list[list[tuple]]:
    if not grouping_sets:
        raise ValueError("The 'grouping_sets' parameter cannot be empty.")

    query = self._search(domain)
    result = [[] for __ in grouping_sets]
    if query.is_empty():
        return result

    # grouping_sets: [(a, b), (a), ()]
    # all_groupby_specs: (a, b)
    all_groupby_specs = tuple(unique(spec for groupby in grouping_sets for spec in groupby))

    # --- Many2many Special Handling ---
    many2many_groupby_specs = []
    if len(grouping_sets) > 1:  # many2many logic only applies if we have multiple groupings

        def might_duplicate_rows(model, spec) -> bool:
            fname, property_name, __ = parse_read_group_spec(spec)
            field = model._fields[fname]
            if field.type == 'properties':
                definition = self.get_property_definition(f"{fname}.{property_name}")
                property_type = definition.get('type')
                return property_type in ('tags', 'many2many')

            if property_name:
                assert field.type == 'many2one'
                return might_duplicate_rows(self.env[field.comodel_name], property_name)

            return field.type == 'many2many'

        for spec in all_groupby_specs:
            if might_duplicate_rows(self, spec):
                many2many_groupby_specs.append(spec)

    if (
        many2many_groupby_specs and
        # If aggregates are sensitive to row duplication (like sum, avg), we must isolate M2M groupings.
        any(
            not aggregate.endswith(
                (':max', ':min', ':bool_and', ':bool_or', ':array_agg_distinct', ':recordset', ':count_distinct'),
            )
            for aggregate in aggregates if aggregate != '__count'
        )
    ):
        # The following logic is a recursive decomposition strategy. It's complex
        # but necessary to prevent M2M joins from corrupting aggregates in other grouping sets.
        # We find all combinations of M2M fields and create a sub-call for grouping sets
        # that share that exact combination of M2M fields.

        # ['A', 'B', 'C'] => [('A', 'B', 'C'), ('A', 'B'), ('A', 'C'), ('B', 'C'), ('A',), ('B',), ('C',), ()]
        m2m_combinaisons = (
            groupby for i in range(len(many2many_groupby_specs), -1, -1)
            for groupby in itertools.combinations(many2many_groupby_specs, i)
        )

        grouping_sets_to_process = dict(enumerate(grouping_sets))
        batched_calls = []  # [([groupby, ...], [index_result, ...])]

        for m2m_comb in m2m_combinaisons:
            if not grouping_sets_to_process:
                break
            sub_grouping_sets = []
            sub_result_indexes = []
            for i, groupby in list(grouping_sets_to_process.items()):
                if all(m2m in groupby for m2m in m2m_comb):
                    sub_grouping_sets.append(groupby)
                    sub_result_indexes.append(i)
                    grouping_sets_to_process.pop(i)

            if sub_grouping_sets:
                batched_calls.append((sub_result_indexes, sub_grouping_sets))

        assert not grouping_sets_to_process
        # If the problem was decomposed, make recursive calls and assemble results.
        if len(batched_calls) > 1:
            for indexes, sub_grouping_sets in batched_calls:

                sub_order_parts = []
                all_sub_groupby = {spec for groupby in sub_grouping_sets for spec in groupby}
                for order_part in (order or '').split(','):
                    order_part = order_part.strip()
                    if not any(
                        order_part.startswith(spec)
                        for spec in all_groupby_specs if spec not in all_sub_groupby
                    ):
                        sub_order_parts.append(order_part)

                sub_results = self._read_grouping_sets(
                    domain, sub_grouping_sets, aggregates=aggregates, order=",".join(sub_order_parts),
                )
                for index, subresult in zip(indexes, sub_results):
                    result[index] = subresult
            return result

    elif many2many_groupby_specs and '__count' in aggregates:
        # Efficiently handle '__count' with M2M fields by using a distinct count on 'id'
        # without making another _read_grouping_sets (this is the very common case).
        aggregates = tuple(
            aggregate if aggregate != '__count' else 'id:count_distinct'
            for aggregate in aggregates
        )
        if order:
            order = order.replace('__count', 'id:count_distinct')

    # --- SQL Query Construction ---
    groupby_terms: dict[str, SQL] = {
        spec: self._read_group_groupby(query.table, spec) for spec in all_groupby_specs
    }
    aggregates_terms: list[SQL] = [
        self._read_group_select(query.table, spec) for spec in aggregates
    ]
    if groupby_terms:
        # grouping_select_sql: GROUPING(a, b)
        grouping_select_sql = SQL("GROUPING(%s)", SQL(", ").join(unique(groupby_terms.values())))
    else:
        # GROUPING() is invalid SQL, so we use the 0 as literal
        grouping_select_sql = SQL("0")

    select_args = [grouping_select_sql, *groupby_terms.values(), *aggregates_terms]

    # _read_group_orderby may change groupby_terms then it is necessary to be call before
    query.order = self._read_group_orderby(query.table, order, groupby_terms)
    # GROUPING SET ((a, b), (a), ())
    grouping_sets_sql = [
        SQL("(%s)", SQL(", ").join(unique(groupby_terms[groupby_spec] for groupby_spec in grouping_set)))
        for grouping_set in grouping_sets
    ]
    query.groupby = SQL("GROUPING SETS (%s)", SQL(", ").join(unique(grouping_sets_sql)))

    # This handles the case where `order` adds columns that must also be in `GROUP BY`.
    # Rebuild the grouping sets to include these extra terms.

    # row_values: [(GROUPING(...), a1, b1, aggregates...), (GROUPING(...), a2, b2, aggregates...), ...]
    row_values = self.env.execute_query(query.select(*select_args))

    if not row_values:  # shortcut
        return result

    # --- Result Post-Processing ---
    # This is the core of the result dispatching logic. It uses the integer
    # returned by GROUPING() as a key to map each result row to the correct
    # grouping set defined by the user.
    aggregates_indexes = tuple(range(len(all_groupby_specs), len(all_groupby_specs) + len(aggregates)))

    # Map each possible GROUPING() bitmask to the corresponding result lists and value
    # extractors: several grouping sets can share the same bitmask (either because
    # they are literally the same groupby list: [['foo'], ['foo']], or because one of them
    # repeats a term [['foo'], ['foo', 'foo']], so a single SQL result row may need to
    # be dispatched to more than one of them.
    # {GROUPING(...): [(append_method, extractor_method), ...]}
    mask_grouping_mapping = defaultdict(list)

    # Create a mapping from each unique SQL GROUP BY term to its bitmask value.
    # The terms are reversed to match the PostgreSQL logic where the bitmask was
    # calculated from right to left (LSB first).
    # See PostgreSQL Doc: https://www.postgresql.org/docs/17/functions-aggregate.html#Grouping-Operations
    mask_sql_mapping = {
        sql_groupby: 1 << i
        for i, sql_groupby in enumerate(unique(reversed(groupby_terms.values())))
    }

    for result_index, groupby in enumerate(grouping_sets):
        # E.g. GROUPING SET ((a, b), (a), ())
        # GROUPING(a, b): a and b included = 0, a included = 1, b included = 2, none included = 3
        sql_terms = {groupby_terms[groupby_spec] for groupby_spec in groupby}
        groupby_mask = sum(
            mask for sql_term, mask in mask_sql_mapping.items()
            # each bit is 0 if the corresponding expression is included in the grouping criteria
            # of the grouping set generating the current result row, and 1 if it is not included.
            if sql_term not in sql_terms
        )

        mask_grouping_mapping[groupby_mask].append((
            result[result_index].append,
            itemgetter_tuple(list(itertools.chain(
                (all_groupby_specs.index(groupby_spec) for groupby_spec in groupby),
                aggregates_indexes,
            ))),
        ))

    aggregates_start_index = len(all_groupby_specs) + 1
    # Transpose rows to columns for efficient, column-wise post-processing.
    columns = list(zip(*row_values))
    # The first column is the grouping mask
    dispatch_info = map(mask_grouping_mapping.__getitem__, columns[0])
    # Post-process values column by column
    columns = [
        *map(self._read_group_postprocess_groupby, all_groupby_specs, columns[1:aggregates_start_index]),
        *map(self._read_group_postprocess_aggregate, aggregates, columns[aggregates_start_index:]),
    ]

    # result: [
    #   [(a1, b1, <aggregates>), (a2, b2, <aggregates>), ...],
    #   [(a1, <aggregates>), (a2, <aggregates>), ...],
    #   [(<aggregates>)],
    # ]
    for append_extractors, *row in zip(dispatch_info, *columns, strict=True):
        for append_method, extractor in append_extractors:
            append_method(extractor(row))

    return result


def read_group(self, domain: DomainType, groupby: Sequence[str]=(), aggregates: Sequence[str]=(), having: DomainType=(), offset: int=0, limit: int | None=None, order: str | None=None) -> list[tuple]:
    groups = self._read_group(domain, groupby, aggregates, having=having, offset=offset, limit=limit, order=order)
    if not groups:
        return groups
    # check the first line for data types, transform records into ids (id for groupby, ids for aggregates)
    decoders = []
    for i, value in enumerate(groups[0]):
        if isinstance(value, BaseModel):
            if i < len(groupby):
                decoders.append(lambda v: v.id)
            else:
                decoders.append(lambda v: v.ids)
        else:
            decoders.append(None)
    if any(decoders):
        decoders = [d or (lambda x: x) for d in decoders]
        groups = [
            # much faster version of :
            # tuple(dec(val) for dec, val in zip(decoders, group))
            tuple(map(call, decoders, group))
            for group in groups
        ]
    return groups


def _read_group(self, domain: DomainType, groupby: Sequence[str]=(), aggregates: Sequence[str]=(), having: DomainType=(), offset: int=0, limit: int | None=None, order: str | None=None) -> list[tuple]:
    query = self._search(domain)
    if query.is_empty():
        if not groupby:
            # when there is no group, postgresql always return a row
            return [tuple(
                self._read_group_empty_value(spec)
                for spec in itertools.chain(groupby, aggregates)
            )]
        return []

    query.limit = limit
    query.offset = offset

    groupby_terms: dict[str, SQL] = {
        spec: self._read_group_groupby(query.table, spec)
        for spec in groupby
    }
    aggregates_terms: list[SQL] = [
        self._read_group_select(query.table, spec)
        for spec in aggregates
    ]
    select_args = [*[groupby_terms[spec] for spec in groupby], *aggregates_terms]
    if groupby_terms:
        query.order = self._read_group_orderby(query.table, order, groupby_terms)
        query.groupby = SQL(", ").join(groupby_terms.values())
        query.having = self._read_group_having(query.table, list(having))
    elif not select_args:
        raise ValueError(self.env._("Need groupby or aggregates."))

    # row_values: [(a1, b1, c1), (a2, b2, c2), ...]
    row_values = self.env.execute_query(query.select(*select_args))

    if not row_values:
        return row_values

    # post-process values column by column
    column_iterator = zip(*row_values)

    # column_result: [(a1, a2, ...), (b1, b2, ...), (c1, c2, ...)]
    column_result = []
    for spec in groupby:
        column = self._read_group_postprocess_groupby(spec, next(column_iterator))
        column_result.append(column)
    for spec in aggregates:
        column = self._read_group_postprocess_aggregate(spec, next(column_iterator))
        column_result.append(column)
    assert next(column_iterator, None) is None

    # return [(a1, b1, c1), (a2, b2, c2), ...]
    return list(zip(*column_result))


def _read_group_select(self, table: TableSQL, aggregate_spec: str) -> SQL:
    if aggregate_spec == '__count':
        return SQL("COUNT(*)")

    fname, property_name, func = parse_read_group_spec(aggregate_spec)

    if property_name:
        raise ValueError(f"Invalid {aggregate_spec!r}, this dot notation is not supported")

    if fname not in self._fields:
        raise ValueError(f"Invalid field {fname!r} on model {self._name!r} for {aggregate_spec!r}.")
    if not func:
        raise ValueError(f"Aggregate method is mandatory for {fname!r}")

    table = table._with_model(table._model.with_context(_generating_sql_for_fields=True))
    field = self._fields[fname]
    if func == 'sum_currency':
        if field.type != 'monetary':
            raise ValueError(f'Aggregator "sum_currency" only works on currency field for {fname!r}')

        currency_field_name = field.get_currency_field(self)
        rate_sql = self.env['res.currency']._current_rate_sql(table, currency_field_name)
        return SQL("SUM(%s / %s)", table[fname], rate_sql)

    if func not in READ_GROUP_AGGREGATE:
        raise ValueError(f"Invalid aggregate method {func!r} for {aggregate_spec!r}.")

    if func == 'recordset' and not (field.relational or fname == 'id'):
        raise ValueError(f"Aggregate method {func!r} can be only used on relational field (or id) (for {aggregate_spec!r}).")

    sql_field = table[fname]
    return READ_GROUP_AGGREGATE[func](table, sql_field)


def _read_group_groupby(self, table: TableSQL, groupby_spec: str) -> SQL:
    fname, seq_fnames, granularity = parse_read_group_spec(groupby_spec)

    assert table._model._name == self._name
    if fname not in self._fields:
        raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")
    field = self._fields[fname]
    table = table._with_model(table._model.with_context(_generating_sql_for_fields=True))

    if field.type == 'properties':
        sql_expr = table[fname][seq_fnames]
        if granularity:
            try:
                sql_expr = sql_expr[granularity]
            except (TypeError, AttributeError, ValueError):
                raise ValueError(f"Invalid granularity in {groupby_spec!r}")

        return sql_expr

    elif seq_fnames:
        if field.type != 'many2one':
            raise ValueError(f"Only many2one path is accepted for the {groupby_spec!r} groupby spec")

        cotable = field.join(table)
        return cotable._model._read_group_groupby(cotable, f"{seq_fnames}:{granularity}" if granularity else seq_fnames)

    elif field.type == 'many2many':
        sql_expr = field.join(table, only_ids=True).id

    elif field.type in ('datetime', 'date'):
        if not granularity:
            raise ValueError(f"Granularity not set on a date(time) field: {groupby_spec!r}")
        sql_expr = table[fname][granularity]
        granularity = None

    elif field.type == 'boolean':
        sql_expr = SQL("COALESCE(%s, FALSE)", table[fname])

    else:
        sql_expr = table[fname]

    if granularity:
        raise ValueError(f"Granularity set on a no-datetime field or property: {groupby_spec!r}")
    return sql_expr


def _read_group_having(self, table: TableSQL, having_domain: list) -> SQL:
    if not having_domain:
        return SQL()

    stack: list[SQL] = []
    SUPPORTED = ('in', 'not in', '<', '>', '<=', '>=', '=', '!=')
    for item in reversed(having_domain):
        if item == '!':
            stack.append(SQL("(NOT %s)", stack.pop()))
        elif item == '&':
            stack.append(SQL("(%s AND %s)", stack.pop(), stack.pop()))
        elif item == '|':
            stack.append(SQL("(%s OR %s)", stack.pop(), stack.pop()))
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            left, operator, right = item
            if operator not in SUPPORTED:
                raise ValueError(f"Invalid having clause {item!r}: supported comparators are {SUPPORTED}")
            sql_left = self._read_group_select(table, left)
            stack.append(SQL("%s%s%s", sql_left, SQL_OPERATORS[operator], right))
        else:
            raise ValueError(f"Invalid having clause {item!r}: it should be a domain-like clause")

    while len(stack) > 1:
        stack.append(SQL("(%s AND %s)", stack.pop(), stack.pop()))

    return stack[0]


def _read_group_orderby(self, table: TableSQL, order: str, groupby_terms: dict[str, SQL]) -> SQL:
    if order:
        traverse_many2one = True
    else:
        order = ','.join(groupby_terms)
        traverse_many2one = False

    if not order:
        return SQL()

    orderby_terms = []

    for order_part in order.split(','):
        order_match = regex_order_part_read_group.fullmatch(order_part)
        if not order_match:
            raise ValueError(f"Invalid order {order!r} for _read_group()")
        term = order_match['term']
        direction = (order_match['direction'] or 'ASC').upper()
        nulls = (order_match['nulls'] or '').upper()

        sql_direction = (
            SQL('ASC') if direction == 'ASC'
            else SQL('DESC') if direction == 'DESC'
            else SQL()
        )
        sql_nulls = (
            SQL('NULLS FIRST') if nulls == 'NULLS FIRST'
            else SQL('NULLS LAST') if nulls == 'NULLS LAST'
            else SQL()
        )

        if term not in groupby_terms:
            try:
                sql_expr = self._read_group_select(table, term)
            except ValueError as e:
                raise ValueError(f"Order term {order_part!r} is not a valid aggregate nor valid groupby") from e
            orderby_terms.append(SQL("%s %s %s", sql_expr, sql_direction, sql_nulls))
            continue

        field = self._fields.get(term)
        __, __, granularity = parse_read_group_spec(term)
        if (
            traverse_many2one and field and field.type == 'many2one'
            and self.env[field.comodel_name]._order != 'id'
        ):
            if sql_order := self._order_to_sql(table, f'{term} {direction} {nulls}'):
                orderby_terms.append(sql_order)
                query = table._query
                if query._order_groupby:
                    query._order_groupby.insert(0, groupby_terms[term])
                    groupby_terms[term] = SQL(", ").join(query._order_groupby)
                    query._order_groupby.clear()
        elif field and field.type == 'selection':
            sql_keys = list(field.get_values(self.env))
            sql_expr = SQL("array_position(%s::text[], %s::text)", sql_keys, groupby_terms[term])
            orderby_terms.append(SQL("%s %s %s", sql_expr, sql_direction, sql_nulls))
        elif granularity == 'day_of_week':
            """
            Day offset relative to the first day of week in the user lang
            formula: ((7 - first_week_day) + day_in_SQL) % 7

                           | week starts on
                       SQL | mon   sun   sat
                           |  1  |  7  |  6   <-- first_week_day (in odoo)
                      -----|-----------------
                mon     1  |  0  |  1  |  2
                tue     2  |  1  |  2  |  3
                wed     3  |  2  |  3  |  4
                thu     4  |  3  |  4  |  5
                fri     5  |  4  |  5  |  6
                sat     6  |  5  |  6  |  0
                sun     0  |  6  |  0  |  1
            """
            first_week_day = int(get_lang(self.env).week_start)
            sql_expr = SQL("mod(7 - %s + %s::int, 7)", first_week_day, groupby_terms[term])
            orderby_terms.append(SQL("%s %s %s", sql_expr, sql_direction, sql_nulls))
        else:
            sql_expr = groupby_terms[term]
            orderby_terms.append(SQL("%s %s %s", sql_expr, sql_direction, sql_nulls))

    return SQL(", ").join(orderby_terms)


def _read_group_empty_value(self, spec):
    if spec == '__count':
        return 0
    fname, chain_fnames, func = parse_read_group_spec(spec)  # func is either None, granularity or an aggregate
    if func in ('count', 'count_distinct'):
        return 0
    if func in ('array_agg', 'array_agg_distinct'):
        return []
    field = self._fields[fname]
    if (not func or func == 'recordset') and (field.relational or fname == 'id'):
        if chain_fnames and field.type == 'many2one':
            groupby_seq = f"{chain_fnames}:{func}" if func else chain_fnames
            model = self.env[field.comodel_name]
            return model._read_group_empty_value(groupby_seq)
        return self.env[field.comodel_name] if field.relational else self.env[self._name]
    return False


def _read_group_postprocess_groupby(self, groupby_spec, raw_values):
    empty_value = self._read_group_empty_value(groupby_spec)

    fname, chain_fnames, granularity = parse_read_group_spec(groupby_spec)
    field = self._fields[fname]

    if field.relational or fname == 'id':
        if chain_fnames and field.relational:
            groupby_seq = f"{chain_fnames}:{granularity}" if granularity else chain_fnames
            model = self.env[field.comodel_name]
            return model._read_group_postprocess_groupby(groupby_seq, raw_values)

        Model = self.pool[field.comodel_name] if field.relational else self.pool[self._name]
        prefetch_ids = tuple(raw_value for raw_value in raw_values if raw_value)

        def recordset(value):
            return Model(self.env, (value,), prefetch_ids) if value else empty_value

        return (recordset(value) for value in raw_values)

    return ((value if value is not None else empty_value) for value in raw_values)


def _read_group_postprocess_aggregate(self, aggregate_spec, raw_values):
    empty_value = self._read_group_empty_value(aggregate_spec)

    if aggregate_spec == '__count':
        return ((value if value is not None else empty_value) for value in raw_values)

    fname, __, func = parse_read_group_spec(aggregate_spec)
    if func == 'recordset':
        field = self._fields[fname]
        Model = self.pool[field.comodel_name] if field.relational else self.pool[self._name]
        prefetch_ids = tuple(unique(
            id_
            for array_values in raw_values if array_values
            for id_ in array_values if id_
        ))

        def recordset(value):
            if not value:
                return empty_value
            ids = tuple(unique(id_ for id_ in value if id_))
            return Model(self.env, ids, prefetch_ids)

        return (recordset(value) for value in raw_values)

    return ((value if value is not None else empty_value) for value in raw_values)


def _read_group_expand_full(self, groups: ModelType, domain: DomainType) -> ModelType:
    return groups.search([])


def _field_to_sql(self, alias: str, field_expr: str, query: Query | None=None) -> SQL:
    fname, property_name = parse_field_expr(field_expr)
    table = TableSQL(alias, self, query)
    sql = table[fname]
    if property_name:
        sql = sql[property_name]
    return sql

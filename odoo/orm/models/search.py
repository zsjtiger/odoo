# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Search: the search domains, the query, the order and the display names of the records."""

from __future__ import annotations

import contextlib
import logging
import re
import typing

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import UserError
from odoo.tools import (
    OrderedSet,
    SQL,
)
from odoo.tools.translate import _


from odoo.orm.core.domains import Domain

from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import (
    parse_field_expr,
    COLLECTION_TYPES,
)

if typing.TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Self
    from odoo.orm.core.types import DomainType, ValuesType


_logger = logging.getLogger('odoo.models')

regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
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


def search_count(self, domain: DomainType, limit: int | None=None) -> int:
    query = self._search(domain, limit=limit)
    return len(query)


def search(self, domain: DomainType, offset: int=0, limit: int | None=None, order: str | None=None) -> Self:
    return self.search_fetch(domain, [], offset=offset, limit=limit, order=order)


def search_fetch(self, domain: DomainType, field_names: Sequence[str] | None=None, offset: int=0, limit: int | None=None, order: str | None=None) -> Self:
    # first determine a query that satisfies the domain and access rules
    query = self._search(domain, offset=offset, limit=limit, order=order or self._order)

    if query.is_empty():
        # optimization: don't execute the query at all
        if not self.env.su:  # check access to fields
            self._determine_fields_to_fetch(field_names)
        return self.browse()

    fields_to_fetch = self._determine_fields_to_fetch(field_names)

    fetched = self._fetch_query(query, fields_to_fetch)
    if not self.env.su:
        self.env._add_to_access_cache(fetched)

    # force computation of fields
    for field_name in (field_names or ()):
        field = self._fields[field_name]
        if not field.store and any(field._cache_missing_ids(fetched)):
            fetched.mapped(field_name)

    return fetched


def _search(self, domain: DomainType, offset: int=0, limit: int | None=None, order: str | None=None, *, active_test: bool=True, bypass_access: bool=False) -> Query:
    if self.env.su or bypass_access:
        sec_domain = Domain.TRUE
    else:
        sec_domain = self._access_domain('read')
        if sec_domain.is_false():
            self.browse().check_access('read')
            domain = Domain.FALSE

    domain = Domain(domain)
    # inactive records unless they were explicitly asked for
    if (
        self._active_name
        and active_test
        and self.env.context.get('active_test', True)
        and not any(leaf.field_expr == self._active_name for leaf in domain.iter_conditions())
    ):
        # try to create the domain close to what it will look like after optimization
        # to avoid reoptimizing it
        domain = Domain(self._active_name, 'in', OrderedSet((True,))) & domain

    # build the query
    domain = domain.optimize_full(self)
    if domain.is_false():
        return self.browse()._as_query()
    query = Query(self)
    if not domain.is_true():
        query.add_where(domain._to_sql(query.table))

    # security access domain
    if not sec_domain.is_true():
        self_sudo = self.sudo().with_context(active_test=False)
        sec_domain = sec_domain.optimize_full(self_sudo, search_domain=domain)
        if sec_domain.is_false():
            return self.browse()._as_query()
        if (
            sec_domain.is_condition('id', 'any!', Query)
            and (ids := sec_domain.value._ids) is not None
        ):
            # optimization: browse ids and filter using the domain
            records = self.browse(ids)
            self.env._add_to_access_cache(records)
            records = records.filtered_domain(domain)
            if order:
                records = records.with_prefetch().sorted(order)
            if offset:
                records = records[offset:]
            if limit:
                records = records[:limit]
            return records._as_query(ordered=bool(order))
        if not sec_domain.is_true():
            query.add_where(sec_domain._to_sql(query.table._with_model(self_sudo)))

    # add order and limits
    if order:
        query.order = self._order_to_sql(query.table, order)

    # In RPC, None is not available; False is used instead to mean "no limit"
    # Note: True is kept for backward-compatibility (treated as 1)
    if limit is not None and limit is not False:
        query.limit = limit
    if offset is not None:
        query.offset = offset

    return query


def _as_query(self, ordered: bool=True) -> Query:
    query = Query(self)
    query.set_result_ids(self._ids, ordered)
    return query


def _check_qorder(self, word: str) -> None:
    if not regex_order.match(word):
        raise UserError(_(
            "Invalid \"order\" specified (%s)."
            " A valid \"order\" specification is a comma-separated list of valid field names"
            " (optionally followed by asc/desc for the direction)",
            word,
        ))


def _order_to_sql(self, table: TableSQL, order: str, reverse: bool=False) -> SQL:
    order = order or self._order
    if not order:
        return SQL()
    self._check_qorder(order)

    terms = []
    for order_part in order.split(','):
        order_match = regex_order.match(order_part)
        assert order_match is not None, "No match found"
        field_name = order_match['field']

        direction = (order_match['direction'] or '').upper()
        nulls = (order_match['nulls'] or '').upper()
        if reverse:
            direction = 'ASC' if direction == 'DESC' else 'DESC'
            if nulls:
                nulls = 'NULLS LAST' if nulls == 'NULLS FIRST' else 'NULLS FIRST'

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

        if property_name := order_match['property']:
            # field_name is an expression
            field_name = f"{field_name}.{property_name}"
        term = self._order_field_to_sql(table, field_name, sql_direction, sql_nulls)
        if term:
            terms.append(term)

    return SQL(", ").join(terms)


def _order_field_to_sql(self, table: TableSQL, field_expr: str, direction: SQL, nulls: SQL) -> SQL:
    # field_name is an expression
    fname, property_name = parse_field_expr(field_expr)
    field = self._fields.get(fname)
    if not field:
        raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

    if field.type == 'many2one':
        seen = self.env.context.get('__m2o_order_seen', ())
        if field in seen:
            return SQL()
        self = self.with_context(__m2o_order_seen=frozenset((field, *seen)))

        # figure out the applicable order_by for the m2o
        # special case: ordering by "x_id.id" doesn't recurse on x_id's comodel
        comodel = self.env[field.comodel_name]
        sql_field = table[fname]
        if property_name == 'id':
            coorder = 'id'
        elif property_name:
            raise ValueError(f"Cannot order by comodel fields in {field_expr!r}")
        else:
            coorder = comodel._order

        if coorder == 'id':
            table._query._order_groupby.append(sql_field)
            return SQL("%s %s %s", sql_field, direction, nulls)

        # instead of ordering by the field's raw value, use the comodel's
        # order on many2one values
        terms = []
        nulls_code = nulls._sql_tuple[0]
        if nulls_code == 'NULLS FIRST':
            terms.append(SQL("%s IS NOT NULL", sql_field))
        elif nulls_code == 'NULLS LAST':
            terms.append(SQL("%s IS NULL", sql_field))

        # LEFT JOIN the comodel table, in order to include NULL values, too
        # Run as sudo because we can order by inaccessible models as we can
        # only order by the default order or the id.
        cotable = table._with_model(self.sudo())._join(fname)

        # delegate the order to the comodel
        reverse = direction._sql_tuple[0] == 'DESC'
        term = comodel._order_to_sql(cotable, coorder, reverse=reverse)
        if term:
            terms.append(term)
        return SQL(", ").join(terms)

    sql_field = table[fname]

    if property_name:
        sql_field = sql_field[property_name]
    if field.type == 'boolean' and field not in self.env.registry.not_null_fields:
        sql_field = SQL("COALESCE(%s, FALSE)", sql_field)
    elif field.type == 'selection':
        sql_keys = list(field.get_values(self.env))
        sql_field = SQL("array_position(%s::text[], %s::text)", sql_keys, sql_field)

    table._query._order_groupby.append(sql_field)

    return SQL("%s %s %s", sql_field, direction, nulls)


def search_read(self, domain: DomainType | None=None, fields: Sequence[str] | None=None, offset: int=0, limit: int | None=None, order: str | None=None, **read_kwargs) -> list[ValuesType]:
    if not fields:
        fields = list(self.fields_get(attributes=()))
    records = self.search_fetch(domain or [], fields, offset=offset, limit=limit, order=order)

    # Method _read_format() ignores 'active_test', but it would forward it
    # to any downstream search call(e.g. for x2m or computed fields), and
    # this is not the desired behavior. The flag was presumably only meant
    # for the main search().
    if 'active_test' in self.env.context:
        context = dict(self.env.context)
        del context['active_test']
        records = records.with_context(context)

    return records._read_format(fnames=fields, **read_kwargs)


def name_search(self, name: str='', domain: DomainType | None=None, operator: str='ilike', limit: int=100) -> list[tuple[int, str]]:
    domain = Domain('display_name', operator, name) & Domain(domain or Domain.TRUE)
    records = self.search_fetch(domain, ['display_name'], limit=limit)
    return [(record.id, record.display_name) for record in records.sudo()]


def name_create(self, name: str) -> tuple[int, str]:
    if not self._rec_name:
        raise NotImplementedError(f"Cannot name_create on {self._name}")
    record = self.create({self._rec_name: name})
    return record.id, record.display_name


def _search_display_name(self, operator, value):
    search_fnames = self._rec_names_search or ([self._rec_name] if self._rec_name else [])
    if not search_fnames:
        _logger.warning("Cannot search on display_name, no _rec_name or _rec_names_search defined on %s", self._name)
        # do not restrain anything
        return Domain.TRUE
    if operator.endswith('like') and not value and '=' not in operator:
        # optimize out the default criterion of ``like ''`` that matches everything
        # return all when operator is positive
        return Domain.FALSE if operator in Domain.NEGATIVE_OPERATORS else Domain.TRUE
    aggregator = Domain.AND if operator in Domain.NEGATIVE_OPERATORS else Domain.OR
    domains = []
    for field_name in search_fnames:
        # field_name may be a sequence of field names (partner_id.name)
        # retrieve the last field in the sequence
        model = self
        for fname in field_name.split('.'):
            if model is None:
                raise ValueError(f"Traversing non-relational field in {self._name}._rec_names_search or {self._name}._rec_name")
            field = model._fields[fname]
            comodel_name = field.comodel_name if field.relational else None
            model = self.env.get(comodel_name) if comodel_name else None
        # depending on the operator, we may need to cast the value to the type of the field
        # ignore if we cannot convert
        if field.relational:
            # relational fields will search on the display_name
            domains.append([(field_name + '.display_name', operator, value)])
        elif operator.endswith('like'):
            domains.append([(field_name, operator, value)])
        elif isinstance(value, COLLECTION_TYPES):
            typed_value = []
            for v in value:
                with contextlib.suppress(ValueError, TypeError):
                    typed_value.append(field.convert_to_write(v, self))
            domains.append([(field_name, operator, typed_value)])
        else:
            with contextlib.suppress(ValueError):
                typed_value = field.convert_to_write(value, self)
                domains.append([(field_name, operator, typed_value)])
            continue
        with contextlib.suppress(ValueError, TypeError):
            # ignore that case if the value doesn't match the field type
            domains.append([(field_name, operator, field.convert_to_write(value, self))])
    return aggregator(domains)


def _compute_display_name(self):
    if self._rec_name:
        convert = self._fields[self._rec_name].convert_to_display_name
        for record in self:
            record.display_name = convert(record[self._rec_name], record)
    else:
        for record in self:
            record.display_name = f"{record._name},{record.id}"

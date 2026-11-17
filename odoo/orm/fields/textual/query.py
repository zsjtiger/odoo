"""The queries on the string fields: the SQL of the translated values and the conditions on them."""

from __future__ import annotations

import typing
from odoo.exceptions import AccessError
from odoo.tools import SQL
from odoo.tools.sql import pattern_to_translated_trigram_pattern, value_to_translated_trigram_pattern
from odoo.tools.text.translate import StoredTranslations
from odoo.orm.core.utils import COLLECTION_TYPES, SQL_OPERATORS

if typing.TYPE_CHECKING:
    from odoo.orm.database.query import TableSQL

from .base import BaseString

def to_sql(self, table: TableSQL) -> SQL:
    if not self.translate or table._model.env.context.get('prefetch_langs'):
        return super(BaseString, self).to_sql(table)
    model = table._model
    sql_field = super(BaseString, self).to_sql(table._with_model(model.with_context(prefetch_langs=True)))
    lang = self.translation_lang(model.env)
    langs = StoredTranslations.fallback_langs(lang)
    sql_field_langs = [SQL("%s->>%s", sql_field, lang) for lang in langs]
    if len(sql_field_langs) == 1:
        return sql_field_langs[0]
    return SQL("COALESCE(%s)", SQL(", ").join(sql_field_langs))


def expression_getter(self, field_expr):
    if field_expr != 'display_name.no_error':
        return super(BaseString, self).expression_getter(field_expr)

    # when searching by display_name, don't raise AccessError but return an
    # empty value instead
    get_display_name = super(BaseString, self).expression_getter('display_name')

    def getter(record):
        try:
            return get_display_name(record)
        except AccessError:
            return ''

    return getter


def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
    # build the condition
    model = table._model
    if self.translate and model.env.context.get('prefetch_langs'):
        model = model.with_context(prefetch_langs=False)
    base_condition = super(BaseString, self).condition_to_sql(table._with_model(model), field_expr, operator, value)

    # faster SQL for index trigrams
    if (
        self.translate
        and value
        and operator in ('in', 'like', 'ilike', '=like', '=ilike')
        and self.index == 'trigram'
        and model.pool.has_trigram
        and (
            isinstance(value, str)
            or (isinstance(value, COLLECTION_TYPES) and all(isinstance(v, str) for v in value))
        )
    ):
        # a prefilter using trigram index to speed up '=', 'like', 'ilike'
        # '!=', '<=', '<', '>', '>=', 'in', 'not in', 'not like', 'not ilike' cannot use this trick
        if operator == 'in' and len(value) == 1:
            value = value_to_translated_trigram_pattern(next(iter(value)))
        elif operator != 'in':
            value = pattern_to_translated_trigram_pattern(value)
        else:
            value = '%'

        if value == '%':
            return base_condition

        raw_sql_field = self.to_sql(table._with_model(model.with_context(prefetch_langs=True)))
        sql_left = SQL("jsonb_path_query_array(%s, '$.*')::text", raw_sql_field)
        sql_operator = SQL_OPERATORS['like' if operator == 'in' else operator]
        sql_right = SQL("%s", self.convert_to_column(value, model, validate=False))
        unaccent = model.env.registry.unaccent
        return SQL(
            "(%s%s%s AND %s)",
            unaccent(sql_left),
            sql_operator,
            unaccent(sql_right),
            base_condition,
        )
    return base_condition

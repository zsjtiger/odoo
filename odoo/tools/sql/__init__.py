# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""SQL helpers of Odoo: the builder of the queries and the schema of the database. The names are re-exported here."""

from .builder import IDENT_RE, LiteralSQL, SQL, _SQLMeta, _TOKEN_REGEX, _TOKEN_SPECIFICATION, escape_like_value, escape_psql, format_query, make_identifier, make_index_name, quoted_identifier, reverse_order
from .tables import SQL_ORDER_BY_TYPE, TableKind, _schema, create_model_table, existing_tables, table_columns, table_exists, table_kind
from .columns import _convert_column, column_exists, convert_column, convert_column_translatable, create_column, drop_not_null, rename_column, set_not_null
from .constraints import _CONFDELTYPES, add_constraint, add_foreign_key, constraint_definition, drop_constraint, fix_foreign_key, get_foreign_keys
from .indexes import add_index, check_index_exist, create_index, drop_index, index_definition, index_exists, pattern_to_translated_trigram_pattern, value_to_translated_trigram_pattern
from .views import drop_depending_views, drop_view_if_exists, get_depending_views
from .rows import increment_fields_skiplock

__all__ = [
    'IDENT_RE',
    'LiteralSQL',
    'SQL',
    'SQL_ORDER_BY_TYPE',
    'TableKind',
    'add_constraint',
    'add_foreign_key',
    'add_index',
    'check_index_exist',
    'column_exists',
    'constraint_definition',
    'convert_column',
    'convert_column_translatable',
    'create_column',
    'create_index',
    'create_model_table',
    'drop_constraint',
    'drop_depending_views',
    'drop_index',
    'drop_not_null',
    'drop_view_if_exists',
    'escape_like_value',
    'escape_psql',
    'existing_tables',
    'fix_foreign_key',
    'format_query',
    'get_depending_views',
    'get_foreign_keys',
    'increment_fields_skiplock',
    'index_definition',
    'index_exists',
    'make_identifier',
    'make_index_name',
    'pattern_to_translated_trigram_pattern',
    'quoted_identifier',
    'rename_column',
    'reverse_order',
    'set_not_null',
    'table_columns',
    'table_exists',
    'table_kind',
    'value_to_translated_trigram_pattern',
]

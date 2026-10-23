"""Indexes of the database: their definitions, their creation and the trigram patterns of the searches."""

from __future__ import annotations

import json
import re
import typing
from odoo.tools.func import deprecated

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.orm.database.sql_db import Cursor

from .builder import SQL
from .tables import _schema

def index_exists(cr: Cursor, indexname: str) -> bool:
    """ Return whether the given index exists. """
    cr.execute(SQL("SELECT 1 FROM pg_indexes WHERE indexname=%s"
                   " AND schemaname = current_schema", indexname))
    return bool(cr.rowcount)


@deprecated("Removed after 20.0")
def check_index_exist(cr, indexname):
    assert index_exists(cr, indexname), f"{indexname} does not exist"


def index_definition(cr: Cursor, indexname: str) -> tuple[str, str | None] | tuple[None, None]:
    """ Read the index definition from the database """
    cr.execute(SQL("""
        SELECT idx.indexdef, d.description
        FROM pg_class c
        JOIN pg_indexes idx ON c.relname = idx.indexname
        LEFT JOIN pg_description d ON c.oid = d.objoid
        WHERE c.relname = %s AND c.relkind = 'i'
          AND c.relnamespace = current_schema::regnamespace
    """, indexname))
    return cr.fetchone() if cr.rowcount else (None, None)


def create_index(
    cr: Cursor,
    indexname: str,
    tablename: str,
    expressions: Iterable,
    method: str = 'btree',
    where='',
    *,
    comment: str | None = None,
    unique: bool = False,
):
    """ Create the given index unless it exists.

    :param cr: The cursor
    :param indexname: The name of the index
    :param tablename: The name of the table
    :param method: The type of the index (default: btree)
    :param where: WHERE clause for the index (default: '')
    :param comment: The comment to set on the index
    :param unique: Whether the index is unique or not (default: False)
    """
    assert expressions, "Missing expressions"
    if index_exists(cr, indexname):
        return
    definition = SQL(
        "USING %s (%s)%s",
        SQL.identifier(method.lower()),
        SQL(", ").join(SQL(expression) for expression in expressions),  # pylint: disable=sql-injection
        SQL(" WHERE %s", SQL(where)) if where else SQL(),  # pylint: disable=sql-injection
    )
    add_index(cr, indexname, tablename, definition, unique=unique, comment=comment)


def add_index(cr: Cursor, indexname: str, tablename: str, definition: str | SQL, *, unique: bool, comment: str | None = ''):
    """ Create an index. """
    if isinstance(definition, str):
        definition = SQL(definition.replace('%', '%%'))  # pylint: disable=sql-injection
    query = SQL(
        "CREATE %sINDEX %s ON %s %s",
        SQL("UNIQUE ") if unique else SQL(),
        SQL.identifier(indexname),
        SQL.identifier(tablename),
        definition,
    )
    query_comment = SQL(
        "COMMENT ON INDEX %s IS %s",
        SQL.identifier(indexname), comment,
    ) if comment else SQL()
    cr.execute(query, log_exceptions=False)
    if query_comment:
        cr.execute(query_comment, log_exceptions=False)
    _schema.debug("Table %r: created index %r (%s)", tablename, indexname, definition)


def drop_index(cr: Cursor, indexname: str, tablename: str):
    """ Drop the given index if it exists. """
    cr.execute(SQL("DROP INDEX IF EXISTS %s", SQL.identifier(indexname)))
    _schema.debug("Table %r: dropped index %r", tablename, indexname)


def value_to_translated_trigram_pattern(value: str) -> str:
    """ Escape value to match a translated field's trigram index content

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original text needs to be JSON-escaped correctly to match it.

    :param value: value provided in domain
    :return: a pattern to match the indexed text
    """
    if len(value) < 3:
        # matching less than 3 characters will not take advantage of the index
        return '%'

    # apply JSON escaping to value; the argument ensure_ascii=False prevents
    # json.dumps from escaping unicode to ascii, which is consistent with the
    # index function jsonb_path_query_array("column_name", '$.*')::text
    json_escaped = json.dumps(value, ensure_ascii=False)[1:-1]

    # apply PG wildcard escaping to JSON-escaped text
    wildcard_escaped = re.sub(r'(_|%|\\)', r'\\\1', json_escaped)

    # add wildcards around it to get the pattern
    return f"%{wildcard_escaped}%"


def pattern_to_translated_trigram_pattern(pattern: str) -> str:
    """ Escape pattern to match a translated field's trigram index content

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original pattern needs to be JSON-escaped correctly to match it.

    :param str pattern: value provided in domain
    :return: a pattern to match the indexed text
    """
    # find the parts around (non-escaped) wildcard characters (_, %)
    sub_patterns = re.findall(r'''
        (
            (?:.)*?           # 0 or more charaters including the newline character
            (?<!\\)(?:\\\\)*  # 0 or even number of backslashes to promise the next wildcard character is not escaped
        )
        (?:_|%|$)             # a non-escaped wildcard charater or end of the string
        ''', pattern, flags=re.VERBOSE | re.DOTALL)

    # unescape PG wildcards from each sub pattern (\% becomes %)
    sub_texts = [re.sub(r'\\(.|$)', r'\1', t, flags=re.DOTALL) for t in sub_patterns]

    # apply JSON escaping to sub texts having at least 3 characters (" becomes \");
    # the argument ensure_ascii=False prevents from escaping unicode to ascii
    json_escaped = [json.dumps(t, ensure_ascii=False)[1:-1] for t in sub_texts if len(t) >= 3]

    # apply PG wildcard escaping to JSON-escaped texts (% becomes \%)
    wildcard_escaped = [re.sub(r'(_|%|\\)', r'\\\1', t) for t in json_escaped]

    # replace the original wildcard characters by %
    return f"%{'%'.join(wildcard_escaped)}%" if wildcard_escaped else "%"

"""Tables of the database: their existence, their kind, their creation and their columns."""

from __future__ import annotations

import enum
import logging
import typing
from collections import defaultdict

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.orm.database.sql_db import Cursor

from .builder import SQL

_schema = logging.getLogger('odoo.schema')


def existing_tables(cr: Cursor, tablenames: Iterable[str]) -> list[str]:
    """ Return the names of existing tables among ``tablenames``. """
    cr.execute(SQL("""
        SELECT c.relname
          FROM pg_class c
         WHERE c.relname IN %s
           AND c.relkind IN ('r', 'v', 'm')
           AND c.relnamespace = current_schema::regnamespace
    """, tuple(tablenames)))
    return [row[0] for row in cr.fetchall()]


def table_exists(cr: Cursor, tablename: str) -> bool:
    """ Return whether the given table exists. """
    return len(existing_tables(cr, {tablename})) == 1


class TableKind(enum.Enum):
    Regular = 'r'
    Temporary = 't'
    View = 'v'
    Materialized = 'm'
    Foreign = 'f'
    Other = None


def table_kind(cr: Cursor, tablename: str) -> TableKind | None:
    """ Return the kind of a table, if ``tablename`` is a regular or foreign
    table, or a view (ignores indexes, sequences, toast tables, and partitioned
    tables; unlogged tables are considered regular)
    """
    cr.execute(SQL("""
        SELECT c.relkind, c.relpersistence
          FROM pg_class c
         WHERE c.relname = %s
           AND c.relnamespace = current_schema::regnamespace
    """, tablename))
    if not cr.rowcount:
        return None

    kind, persistence = cr.fetchone()
    # special case: permanent, temporary, and unlogged tables differ by their
    # relpersistence, they're all "ordinary" (relkind = r)
    if kind == 'r':
        return TableKind.Temporary if persistence == 't' else TableKind.Regular

    try:
        return TableKind(kind)
    except ValueError:
        # NB: or raise? unclear if it makes sense to allow table_kind to
        #     "work" with something like an index or sequence
        return TableKind.Other


SQL_ORDER_BY_TYPE = defaultdict(lambda: 16, {
    'int4': 1,          # 4 bytes aligned on 4 bytes
    'varchar': 2,       # variable aligned on 4 bytes
    'date': 3,          # 4 bytes aligned on 4 bytes
    'jsonb': 4,         # jsonb
    'text': 5,          # variable aligned on 4 bytes
    'numeric': 6,       # variable aligned on 4 bytes
    'bool': 7,          # 1 byte aligned on 1 byte
    'timestamp': 8,     # 8 bytes aligned on 8 bytes
    'float8': 9,        # 8 bytes aligned on 8 bytes
})


def create_model_table(cr: Cursor, tablename: str, comment: str | None = None, columns: Iterable[tuple[str, SQL, str | None]] = ()):
    """ Create the table for a model. """
    colspecs = [
        SQL('id SERIAL NOT NULL'),
        *(SQL("%s %s", SQL.identifier(colname), coldef) for colname, coldef, _ in columns),
        SQL('PRIMARY KEY(id)'),
    ]
    queries = [
        SQL("CREATE TABLE %s (%s)", SQL.identifier(tablename), SQL(", ").join(colspecs)),
    ]
    if comment:
        queries.append(SQL(
            "COMMENT ON TABLE %s IS %s",
            SQL.identifier(tablename), comment,
        ))
    for colname, _, colcomment in columns:
        queries.append(SQL(
            "COMMENT ON COLUMN %s IS %s",
            SQL.identifier(tablename, colname), colcomment,
        ))
    cr.execute(SQL("; ").join(queries))

    _schema.debug("Table %r: created", tablename)


def table_columns(cr: Cursor, tablename: str) -> dict[str, tuple[str, str, int, str]]:
    """ Return a dict mapping column names to their configuration. The latter is
        a dict with the data from the table ``information_schema.columns``.
    """
    # Do not select the field `character_octet_length` from `information_schema.columns`
    # because specific access right restriction in the context of shared hosting (Heroku, OVH, ...)
    # might prevent a postgres user to read this field.
    query = """
        SELECT a.attname AS column_name,
               coalesce(bt.typname, t.typname) AS udt_name,
               information_schema._pg_char_max_length(information_schema._pg_truetypid(a.*, t.*), information_schema._pg_truetypmod(a.*, t.*)) AS character_maximum_length,
               CASE WHEN a.attnotnull OR t.typtype = 'd' AND t.typnotnull THEN 'NO'
                    ELSE 'YES'
               END AS is_nullable
          FROM pg_attribute a
          JOIN pg_class c
            ON a.attrelid = c.oid
          JOIN pg_namespace nc
            ON c.relnamespace = nc.oid
          JOIN pg_type t
            ON a.atttypid = t.oid
     LEFT JOIN (pg_type bt JOIN pg_namespace nbt ON bt.typnamespace = nbt.oid)
            ON t.typtype = 'd'::"char"
           AND t.typbasetype = bt.oid
         WHERE nc.nspname = current_schema
           AND a.attnum > 0
           AND NOT a.attisdropped
           AND c.relkind IN ('r', 'v', 'f', 'p')
           AND (pg_has_role(c.relowner, 'USAGE'::text) OR has_column_privilege(c.oid, a.attnum, 'SELECT, INSERT, UPDATE, REFERENCES'))
           AND c.relname=%s
    """
    cr.execute(SQL(query, tablename))
    return {row['column_name']: row for row in cr.dictfetchall()}

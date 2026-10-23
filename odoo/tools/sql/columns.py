"""Columns of the database: their creation, their conversion and their NOT NULL constraints."""

from __future__ import annotations

import typing
import psycopg2

if typing.TYPE_CHECKING:

    from odoo.orm.database.sql_db import Cursor

from .builder import SQL, make_index_name
from .indexes import drop_index
from .tables import _schema
from .views import drop_depending_views

def column_exists(cr: Cursor, tablename: str, columnname: str) -> bool:
    """ Return whether the given column exists. """
    query = """
        SELECT 1
          FROM pg_attribute a
          JOIN pg_class c
            ON a.attrelid = c.oid
          JOIN pg_namespace nc
            ON c.relnamespace = nc.oid
         WHERE nc.nspname = current_schema
           AND a.attnum > 0
           AND NOT a.attisdropped
           AND c.relkind IN ('r', 'v', 'f', 'p')
           AND (pg_has_role(c.relowner, 'USAGE'::text) OR has_column_privilege(c.oid, a.attnum, 'SELECT, INSERT, UPDATE, REFERENCES'))
           AND c.relname=%s
           AND a.attname=%s
    """
    cr.execute(SQL(query, tablename, columnname))
    return cr.rowcount


def create_column(cr: Cursor, tablename: str, columnname: str, columntype: str | SQL, comment: str | None = None):
    """ Create a column with the given type. """
    sql = SQL(
        "ALTER TABLE %s ADD COLUMN %s %s",
        SQL.identifier(tablename),
        SQL.identifier(columnname),
        columntype if isinstance(columntype, SQL) else SQL.identifier(columntype),
    )
    if comment:
        sql = SQL("%s; %s", sql, SQL(
            "COMMENT ON COLUMN %s IS %s",
            SQL.identifier(tablename, columnname), comment,
        ))
    cr.execute(sql)
    _schema.debug("Table %r: added column %r of type %s", tablename, columnname, columntype)


def rename_column(cr: Cursor, tablename: str, columnname1: str, columnname2: str):
    """ Rename the given column. """
    cr.execute(SQL(
        "ALTER TABLE %s RENAME COLUMN %s TO %s",
        SQL.identifier(tablename),
        SQL.identifier(columnname1),
        SQL.identifier(columnname2),
    ))
    _schema.debug("Table %r: renamed column %r to %r", tablename, columnname1, columnname2)


def convert_column(cr: Cursor, tablename: str, columnname: str, columntype: str | SQL):
    """ Convert the column to the given type. """
    if not isinstance(columntype, SQL):
        columntype = SQL.identifier(columntype)
    using = SQL("%s::%s", SQL.identifier(columnname), columntype)
    _convert_column(cr, tablename, columnname, columntype, using)


def convert_column_translatable(cr: Cursor, tablename: str, columnname: str, columntype: str | SQL):
    """ Convert the column from/to a 'jsonb' translated field column. """
    drop_index(cr, make_index_name(tablename, columnname), tablename)
    if columntype == "jsonb" or columntype == SQL("jsonb"):
        using = SQL(
            "CASE WHEN %s IS NOT NULL THEN jsonb_build_object('en_US', %s::varchar) END",
            SQL.identifier(columnname), SQL.identifier(columnname),
        )
    else:
        using = SQL("%s->>'en_US'", SQL.identifier(columnname))
    _convert_column(cr, tablename, columnname, columntype, using)


def _convert_column(cr: Cursor, tablename: str, columnname: str, columntype: str | SQL, using: SQL):
    if not isinstance(columntype, SQL):
        columntype = SQL.identifier(columntype)
    query = SQL(
        "ALTER TABLE %s ALTER COLUMN %s DROP DEFAULT, ALTER COLUMN %s TYPE %s USING %s",
        SQL.identifier(tablename), SQL.identifier(columnname),
        SQL.identifier(columnname), columntype, using,
    )
    try:
        with cr.savepoint(flush=False):
            cr.execute(query, log_exceptions=False)
    except psycopg2.NotSupportedError:
        drop_depending_views(cr, tablename, columnname)
        cr.execute(query)
    _schema.debug("Table %r: column %r changed to type %s", tablename, columnname, columntype)


def set_not_null(cr: Cursor, tablename: str, columnname: str):
    """ Add a NOT NULL constraint on the given column. """
    query = SQL(
        "ALTER TABLE %s ALTER COLUMN %s SET NOT NULL",
        SQL.identifier(tablename), SQL.identifier(columnname),
    )
    cr.execute(query, log_exceptions=False)
    _schema.debug("Table %r: column %r: added constraint NOT NULL", tablename, columnname)


def drop_not_null(cr: str, tablename: str, columnname: str):
    """ Drop the NOT NULL constraint on the given column. """
    cr.execute(SQL(
        "ALTER TABLE %s ALTER COLUMN %s DROP NOT NULL",
        SQL.identifier(tablename), SQL.identifier(columnname),
    ))
    _schema.debug("Table %r: column %r: dropped constraint NOT NULL", tablename, columnname)

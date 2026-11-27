"""Views of the database: the views depending on a table and their removal."""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:

    from odoo.orm.database.sql_db import Cursor

from .builder import SQL
from .tables import TableKind, _schema, table_kind

def drop_depending_views(cr: Cursor, table: str, column: str):
    """drop views depending on a field to allow the ORM to resize it in-place"""
    for v, k in get_depending_views(cr, table, column):
        cr.execute(SQL(
            "DROP %s IF EXISTS %s CASCADE",
            SQL("MATERIALIZED VIEW" if k == "m" else "VIEW"),
            SQL.identifier(v),
        ))
        _schema.debug("Drop view %r", v)


def get_depending_views(cr: Cursor, table: str, column: str) -> list[tuple[str, str]]:
    # http://stackoverflow.com/a/11773226/75349
    cr.execute(SQL("""
        SELECT distinct quote_ident(dependee.relname), dependee.relkind
        FROM pg_depend
        JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
        JOIN pg_class as dependee ON pg_rewrite.ev_class = dependee.oid
        JOIN pg_class as dependent ON pg_depend.refobjid = dependent.oid
        JOIN pg_attribute ON pg_depend.refobjid = pg_attribute.attrelid
            AND pg_depend.refobjsubid = pg_attribute.attnum
        WHERE dependent.relname = %s
        AND dependent.relnamespace = current_schema::regnamespace
        AND pg_attribute.attnum > 0
        AND pg_attribute.attname = %s
        AND dependee.relkind in ('v', 'm')
    """, table, column))
    return cr.fetchall()


def drop_view_if_exists(cr: Cursor, viewname: str):
    kind = table_kind(cr, viewname)
    if kind == TableKind.View:
        cr.execute(SQL("DROP VIEW %s CASCADE", SQL.identifier(viewname)))
    elif kind == TableKind.Materialized:
        cr.execute(SQL("DROP MATERIALIZED VIEW %s CASCADE", SQL.identifier(viewname)))

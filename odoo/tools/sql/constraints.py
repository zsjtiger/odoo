"""Constraints of the database: the definitions, the foreign keys and their repair."""

from __future__ import annotations

import typing
from odoo.tools.func import deprecated

if typing.TYPE_CHECKING:

    from odoo.orm.database.sql_db import Cursor

from .builder import SQL
from .tables import _schema

_CONFDELTYPES = {
    'RESTRICT': 'r',
    'NO ACTION': 'a',
    'CASCADE': 'c',
    'SET NULL': 'n',
    'SET DEFAULT': 'd',
}


def constraint_definition(cr: str, tablename: str, constraintname: str) -> str | None:
    """ Return the given constraint's definition. """
    cr.execute(SQL("""
        SELECT COALESCE(d.description, pg_get_constraintdef(c.oid))
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        LEFT JOIN pg_description d ON c.oid = d.objoid
        WHERE t.relname = %s AND conname = %s
        AND t.relnamespace = current_schema::regnamespace
    """, tablename, constraintname))
    return cr.fetchone()[0] if cr.rowcount else None


def add_constraint(cr: Cursor, tablename: str, constraintname: str, definition: str):
    """ Add a constraint on the given table. """
    query1 = SQL(
        "ALTER TABLE %s ADD CONSTRAINT %s %s",
        SQL.identifier(tablename), SQL.identifier(constraintname), SQL(definition.replace('%', '%%')),  # pylint: disable=sql-injection
    )
    query2 = SQL(
        "COMMENT ON CONSTRAINT %s ON %s IS %s",
        SQL.identifier(constraintname), SQL.identifier(tablename), definition,
    )
    cr.execute(query1, log_exceptions=False)
    cr.execute(query2, log_exceptions=False)
    _schema.debug("Table %r: added constraint %r as %s", tablename, constraintname, definition)


def drop_constraint(cr: Cursor, tablename: str, constraintname: str):
    """ Drop the given constraint. """
    cr.execute(SQL(
        "ALTER TABLE %s DROP CONSTRAINT %s",
        SQL.identifier(tablename), SQL.identifier(constraintname),
    ))
    _schema.debug("Table %r: dropped constraint %r", tablename, constraintname)


def add_foreign_key(cr: Cursor, tablename1: str, columnname1: str, tablename2: str, columnname2: str, ondelete: str):
    """ Create the given foreign key, and return ``True``. """
    cr.execute(SQL(
        "ALTER TABLE %s ADD FOREIGN KEY (%s) REFERENCES %s(%s) ON DELETE %s",
        SQL.identifier(tablename1), SQL.identifier(columnname1),
        SQL.identifier(tablename2), SQL.identifier(columnname2),
        SQL(ondelete),  # pylint: disable=sql-injection
    ))
    _schema.debug("Table %r: added foreign key %r references %r(%r) ON DELETE %s",
                  tablename1, columnname1, tablename2, columnname2, ondelete)


def get_foreign_keys(cr: Cursor, tablename1: str, columnname1: str, tablename2: str, columnname2: str, ondelete: str) -> list[str]:
    deltype = _CONFDELTYPES[ondelete.upper()]
    cr.execute(SQL(
        """
            SELECT fk.conname as name
            FROM pg_constraint AS fk
            JOIN pg_class AS c1 ON fk.conrelid = c1.oid
            JOIN pg_class AS c2 ON fk.confrelid = c2.oid
            JOIN pg_attribute AS a1 ON a1.attrelid = c1.oid AND fk.conkey[1] = a1.attnum
            JOIN pg_attribute AS a2 ON a2.attrelid = c2.oid AND fk.confkey[1] = a2.attnum
            WHERE fk.contype = 'f'
            AND c1.relname = %s
            AND a1.attname = %s
            AND c2.relname = %s
            AND a2.attname = %s
            AND c1.relnamespace = current_schema::regnamespace
            AND fk.confdeltype = %s
        """,
        tablename1, columnname1, tablename2, columnname2, deltype,
    ))
    return [r[0] for r in cr.fetchall()]


@deprecated("Removed after 20.0")
def fix_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete):
    """ Update the foreign keys between tables to match the given one, and
        return ``True`` if the given foreign key has been recreated.
    """
    # Do not use 'information_schema' here, as those views are awfully slow!
    deltype = _CONFDELTYPES.get(ondelete.upper(), 'a')
    cr.execute(SQL(
        """ SELECT con.conname, c2.relname, a2.attname, con.confdeltype as deltype
              FROM pg_constraint as con, pg_class as c1, pg_class as c2,
                   pg_attribute as a1, pg_attribute as a2
             WHERE con.contype='f' AND con.conrelid=c1.oid AND con.confrelid=c2.oid
               AND array_lower(con.conkey, 1)=1 AND con.conkey[1]=a1.attnum
               AND array_lower(con.confkey, 1)=1 AND con.confkey[1]=a2.attnum
               AND a1.attrelid=c1.oid AND a2.attrelid=c2.oid
               AND c1.relname=%s AND a1.attname=%s
               AND c1.relnamespace = current_schema::regnamespace """,
        tablename1, columnname1,
    ))
    found = False
    for fk in cr.fetchall():
        if not found and fk[1:] == (tablename2, columnname2, deltype):
            found = True
        else:
            drop_constraint(cr, tablename1, fk[0])
    if found:
        return False
    add_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete)
    return True

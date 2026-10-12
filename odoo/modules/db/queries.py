"""Queries on the databases: their names, their existence, their extensions and their administration checks."""

from __future__ import annotations

import logging
import os
import re
import typing
from contextlib import closing
from datetime import datetime
from enum import IntEnum
import psycopg2
import odoo.api
import odoo.modules
import odoo.modules.neutralize
import odoo.release
import odoo.orm.database.sql_db
import odoo.tools
from odoo.exceptions import AccessDenied, UserError
from odoo.tools import config

if typing.TYPE_CHECKING:
    from odoo.orm.database.sql_db import BaseCursor, Cursor


_logger = logging.getLogger('odoo.modules.db')


DB_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]+$')


def is_initialized(cr: Cursor) -> bool:
    """ Check if a database has been initialized for the ORM.

    The database can be initialized with the 'initialize' function below.

    """
    return odoo.tools.sql.table_exists(cr, 'ir_module_module')


class FunctionStatus(IntEnum):
    MISSING = 0  # function is not present (falsy)
    PRESENT = 1  # function is present but not indexable (not immutable)
    INDEXABLE = 2  # function is present and indexable (immutable)


def has_unaccent(cr: BaseCursor) -> FunctionStatus:
    """ Test whether the database has function 'unaccent' and return its status.

    The unaccent is supposed to be provided by the PostgreSQL unaccent contrib
    module but any similar function will be picked by OpenERP.

    :rtype: FunctionStatus
    """
    cr.execute("""
        SELECT p.provolatile
        FROM pg_proc p
        WHERE p.proname = 'unaccent'
              AND p.pronamespace = current_schema::regnamespace
              AND p.pronargs = 1
    """)
    result = cr.fetchone()
    if not result:
        return FunctionStatus.MISSING
    # The `provolatile` of unaccent allows to know whether the unaccent function
    # can be used to create index (it should be 'i' - means immutable), see
    # https://www.postgresql.org/docs/current/catalog-pg-proc.html.
    return FunctionStatus.INDEXABLE if result[0] == 'i' else FunctionStatus.PRESENT


def has_trigram(cr: BaseCursor) -> bool:
    """ Test if the database has the a word_similarity function.

    The word_similarity is supposed to be provided by the PostgreSQL built-in
    pg_trgm module but any similar function will be picked by Odoo.

    """
    cr.execute("SELECT proname FROM pg_proc WHERE proname='word_similarity'")
    return len(cr.fetchall()) > 0


def verify_db_management_enabled() -> None:
    """
    Verify that the database manager is enabled in the configuration. It
    verifies that ``--no-database-list`` is absent from the CLI and that
    ``list_db=0`` is absent from the odoorc configuration file.
    """
    if not odoo.tools.config['list_db']:
        e = "Database management functions blocked, admin disabled database listing."
        raise AccessDenied(e)


def verify_admin_password(passwd: str) -> None:
    """
    Verify that the admin password matches the one saved in the odoorc
    configuration file. It raises an AccessDenied when the verification
    fails.

    The password can instead be ``odoo.modules.db.SKIP_ADMIN_PASSWORD``
    which is a special flag to bypass the verification.
    """
    if not passwd or not odoo.tools.config.verify_admin_password(passwd):
        e = "Database management function blocked, bad admin password."
        raise AccessDenied(e)


def _check_faketime_mode(db_name: str) -> None:
    if not os.getenv('ODOO_FAKETIME_TEST_MODE'):
        return
    if db_name not in odoo.tools.config['db_name']:
        return
    try:
        db = odoo.orm.database.sql_db.db_connect(db_name)
        with db.cursor() as cursor:
            cursor.execute("SELECT (pg_catalog.now() AT TIME ZONE 'UTC');")
            server_now = cursor.fetchone()[0]
            time_offset = (datetime.now() - server_now).total_seconds()

            cursor.execute("""
                CREATE OR REPLACE FUNCTION public.now()
                    RETURNS timestamp with time zone AS $$
                        SELECT pg_catalog.now() +  %s * interval '1 second';
                    $$ LANGUAGE sql;
            """, (int(time_offset), ))
            cursor.execute("SELECT (now() AT TIME ZONE 'UTC');")
            new_now = cursor.fetchone()[0]
            _logger.info("Faketime mode, new cursor now is %s", new_now)
            cursor.commit()
    except psycopg2.Error:
        _logger.warning("Unable to set fakedtimed NOW()", exc_info=True)


class DatabaseExists(UserError, ValueError):
    pass


def list_dbs(*, force=False):
    if not force:
        verify_db_management_enabled()

    if not odoo.tools.config['dbfilter'] and odoo.tools.config['db_name']:
        # In case --db-filter is not provided and --database is passed, Odoo will not
        # fetch the list of databases available on the postgres server and instead will
        # use the value of --database as comma seperated list of exposed databases.
        return sorted(odoo.tools.config['db_name'])

    chosen_template = odoo.tools.config['db_template']
    ignore_templates_list = tuple({'postgres', chosen_template})
    db = odoo.orm.database.sql_db.db_connect(config['db_system'])
    with closing(db.cursor()) as cr:
        try:
            cr.execute("""
                SELECT datname
                  FROM pg_database
                 WHERE datdba = (
                      SELECT usesysid
                        FROM pg_user
                       WHERE usename = current_user
                   )
                   AND NOT datistemplate
                   AND datallowconn
                   AND datname NOT IN %s
              ORDER BY datname
            """, (ignore_templates_list,))
            return [name for (name,) in cr.fetchall()]
        except psycopg2.Error:
            _logger.exception("Listing databases failed:")
            return []


def exist(db_name):
    try:
        odoo.orm.database.sql_db.db_connect(db_name).cursor().close()
    except psycopg2.OperationalError:
        return False
    else:
        return True

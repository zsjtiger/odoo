"""Management of the databases: their creation, duplication, drop, dump, restore and renaming."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import typing
import zipfile
from contextlib import closing, suppress
import psycopg2
import odoo.api
import odoo.modules
import odoo.modules.neutralize
import odoo.release
import odoo.orm.database.sql_db
import odoo.tools
from odoo.tools import SQL, config
from odoo.tools.system import osutil
from odoo.tools.misc import exec_pg_environ, find_pg_tool
from odoo.tools.sql import quoted_identifier

if typing.TYPE_CHECKING:
    from odoo.orm.database.sql_db import Cursor

from .init import _initialize_db
from .queries import DB_NAME_RE, DatabaseExists, _check_faketime_mode, exist

_logger = logging.getLogger('odoo.modules.db')


def _create_empty_database(db_name: str) -> None:
    db_system_name = config['db_system']
    try:
        sys_cr = odoo.orm.database.sql_db.db_connect(db_system_name).cursor()
    except psycopg2.errors.OperationalError:
        # If we use the `db_name` as the system database and we are trying to
        # create it, try to use postgres as the system database.
        if db_system_name == 'postgres' or db_system_name != db_name:
            raise
        _logger.info("Defaulting to 'postgres' system database for database creation")
        sys_cr = odoo.orm.database.sql_db.db_connect('postgres').cursor()
    with closing(sys_cr) as cr:
        cr.execute("SELECT datname FROM pg_database WHERE datname = %s",
                   (db_name,), log_exceptions=False)
        if cr.fetchall():
            _check_faketime_mode(db_name)
            e = f"Database {db_name!r} already exists!"
            raise DatabaseExists(e)
        # database-altering operations cannot be executed inside a transaction
        cr.rollback()
        cr._cnx.autocommit = True

        # 'C' collate is only safe with template0, but provides more useful indexes
        chosen_template = odoo.tools.config['db_template']
        cr.execute(SQL(
            "CREATE DATABASE %s ENCODING 'unicode' %s TEMPLATE %s",
            quoted_identifier(cr, db_name),
            SQL("LC_COLLATE 'C'") if chosen_template == 'template0' else SQL(""),
            quoted_identifier(cr, chosen_template),
        ))

    # TODO: add --extension=trigram,unaccent
    try:
        db = odoo.orm.database.sql_db.db_connect(db_name)
        with db.cursor() as cr:
            cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            if odoo.tools.config['unaccent']:
                cr.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
                # From PostgreSQL's point of view, making 'unaccent' immutable is incorrect
                # because it depends on external data - see
                # https://www.postgresql.org/message-id/flat/201012021544.oB2FiTn1041521@wwwmaster.postgresql.org#201012021544.oB2FiTn1041521@wwwmaster.postgresql.org
                # But in the case of Odoo, we consider that those data don't
                # change in the lifetime of a database. If they do change, all
                # indexes created with this function become corrupted!
                cr.execute("ALTER FUNCTION unaccent(text) IMMUTABLE")
    except psycopg2.Error as e:
        _logger.warning("Unable to create PostgreSQL extensions : %s", e)
    _check_faketime_mode(db_name)

    # restore legacy behaviour on pg15+
    try:
        db = odoo.orm.database.sql_db.db_connect(db_name)
        with db.cursor() as cr:
            cr.execute("GRANT CREATE ON SCHEMA PUBLIC TO PUBLIC")
    except psycopg2.Error as e:
        _logger.warning("Unable to make public schema public-accessible: %s", e)


def create(
    db_name: str,
    *,
    demo: bool,
    user_login: str = 'admin',
    user_password: str,
    lang: str,
    country_code: str | None = None,
    phone: str | None = None,
):
    """
    Create a new database (it must not exists) and install the necessary
    base modules.
    """
    if not DB_NAME_RE.fullmatch(db_name):
        e = f"Invalid {db_name=!r}"
        raise ValueError(e)
    _logger.info("Create database `%s`.", db_name)
    _create_empty_database(db_name)
    return _initialize_db(
        db_name,
        demo=demo,
        user_login=user_login,
        user_password=user_password,
        lang=lang,
        country_code=country_code,
        phone=phone,
    )


def duplicate(
    db_original_name: str,
    db_name: str,
    *,
    neutralize_database: bool = False,
) -> None:
    """
    Create a new database and filestore ``db_name`` (it must not exists)
    using ``db_original_name`` as template. If ``neutralize_database``
    is True then the new database is neutralized.
    """
    if not DB_NAME_RE.fullmatch(db_name):
        e = f"Invalid {db_name=!r}"
        raise ValueError(e)
    _logger.info("Duplicate database `%s` to `%s`.", db_original_name, db_name)
    odoo.orm.database.sql_db.close_db(db_original_name)
    db = odoo.orm.database.sql_db.db_connect(config['db_system'])
    with closing(db.cursor()) as cr:
        # database-altering operations cannot be executed inside a transaction
        cr._cnx.autocommit = True
        _drop_conn(cr, db_original_name)
        cr.execute(SQL(
            "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
            quoted_identifier(cr, db_name),
            quoted_identifier(cr, db_original_name),
        ))

    if neutralize_database:
        # Neutralize the database before it becomes visible to the cron workers
        with odoo.orm.database.sql_db.db_connect(db_name).cursor() as cr:
            odoo.modules.neutralize.neutralize_database(cr)

    registry = odoo.modules.registry.Registry.new(db_name)
    with registry.cursor() as cr:
        # force generation of a new dbuuid
        env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
        env['ir.config_parameter'].init(force=True)

    from_fs = odoo.tools.config.filestore(db_original_name)
    to_fs = odoo.tools.config.filestore(db_name)
    if os.path.exists(from_fs) and not os.path.exists(to_fs):
        shutil.copytree(from_fs, to_fs)


def _drop_conn(cr: Cursor, db_name: str) -> None:
    """
    Try to terminate all other connections that might prevent dropping
    the database.
    """
    assert cr.dbname == config['db_system']
    assert cr._cnx.autocommit
    with suppress(psycopg2.Error):
        cr.execute("""
            SELECT pg_terminate_backend(pid)
              FROM pg_stat_activity
             WHERE datname = %s
               AND pid != pg_backend_pid()
        """, (db_name,))


def drop(db_name: str) -> None:
    """ Drop the database ``db_name`` and remove its filestore. """
    odoo.modules.registry.Registry.delete(db_name)
    odoo.orm.database.sql_db.close_db(db_name)

    db = odoo.orm.database.sql_db.db_connect(config['db_system'])
    with closing(db.cursor()) as cr:
        # database-altering operations cannot be executed inside a transaction
        cr._cnx.autocommit = True
        _drop_conn(cr, db_name)

        try:
            cr.execute(SQL('DROP DATABASE %s', quoted_identifier(cr, db_name)))
        except psycopg2.Error as e:
            e.add_note(f"When trying to drop {db_name}")
            raise
        _logger.info("DROP DB: %s", db_name)

    fs = odoo.tools.config.filestore(db_name)
    if os.path.exists(fs):
        shutil.rmtree(fs)


def _dump_db_manifest(cr: Cursor):
    pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
    cr.execute("SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
    modules = dict(cr.fetchall())
    return {
        'odoo_dump': '1',
        'db_name': cr.dbname,
        'version': odoo.release.version,
        'version_info': odoo.release.version_info,
        'major_version': odoo.release.major_version,
        'pg_version': pg_version,
        'modules': modules,
    }


def dump(
    db_name: str,
    dump_file,
    *,
    backup_format: typing.Literal['zip', 'dump'] = 'zip',
    with_filestore: bool = True,
):
    """Dump database `db` into file-like object `stream` if stream is None
    return a file object with the dump """
    if backup_format not in ('zip', 'dump'):
        e = f"unknown backup_format: {backup_format!r}"
        raise ValueError(e)
    if not exist(db_name):
        e = f"Database {db_name!r} doesn't exist"
        raise ValueError(e)

    _logger.info("DUMP DB: %s format %s %s filestore", db_name, backup_format, 'with' if with_filestore else 'without')

    cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
    env = exec_pg_environ()

    if backup_format == 'zip':
        with tempfile.TemporaryDirectory() as dump_dir:
            if with_filestore:
                filestore = odoo.tools.config.filestore(db_name)
                if os.path.exists(filestore):
                    shutil.copytree(filestore, os.path.join(dump_dir, 'filestore'))
            manifest_path = os.path.join(dump_dir, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as manifest_file:
                with odoo.orm.database.sql_db.db_connect(db_name).cursor() as cr:
                    json.dump(_dump_db_manifest(cr), manifest_file, indent=4)
            cmd.insert(-1, '--file=' + os.path.join(dump_dir, 'dump.sql'))
            subprocess.run(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                check=True,
            )
            osutil.zip_dir(
                dump_dir,
                dump_file,
                include_dir=False,
                fnct_sort=lambda file_name: file_name != 'dump.sql',
            )
    else:
        cmd.insert(-1, '--format=c')
        proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        shutil.copyfileobj(proc.stdout, dump_file)


def restore(
    db_name: str,
    dump_path: os.PathLike,
    *,
    copy: bool = False,
    neutralize_database: bool = False,
) -> None:
    if exist(db_name):
        e = f"Database {db_name!r} already exists"
        raise ValueError(e)

    _logger.info("RESTORING DB: %s", db_name)
    _create_empty_database(db_name)

    filestore_path = None
    with tempfile.TemporaryDirectory() as dump_dir:
        with zipfile.ZipFile(dump_path, 'r') as z:
            # only extract known members!
            filestore = [m for m in z.namelist() if m.startswith('filestore/')]
            z.extractall(dump_dir, ['dump.sql'] + filestore)

            if filestore:
                filestore_path = os.path.join(dump_dir, 'filestore')

        subprocess.run(
            [
                find_pg_tool('psql'),
                '--dbname', db_name,
                '--file', os.path.join(dump_dir, 'dump.sql'),
                '--quiet',
            ],
            env=exec_pg_environ(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=True,
        )

        if neutralize_database:
            # Neutralize the database before it becomes visible to the cron workers
            with odoo.orm.database.sql_db.db_connect(db_name).cursor() as cr:
                odoo.modules.neutralize.neutralize_database(cr)

        registry = odoo.modules.registry.Registry.new(db_name)
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
            if copy:
                # if it's a copy of a database, force generation of a new dbuuid
                env['ir.config_parameter'].init(force=True)

            if filestore_path:
                filestore_dest = env['ir.attachment']._filestore()
                shutil.move(filestore_path, filestore_dest)

    _logger.info("RESTORE DB: %s", db_name)


def rename(
    old_name: str,
    new_name: str,
) -> None:
    odoo.modules.registry.Registry.delete(old_name)
    odoo.orm.database.sql_db.close_db(old_name)

    db = odoo.orm.database.sql_db.db_connect(config['db_system'])
    with closing(db.cursor()) as cr:
        # database-altering operations cannot be executed inside a transaction
        cr._cnx.autocommit = True
        _drop_conn(cr, old_name)
        try:
            cr.execute(SQL(
                'ALTER DATABASE %s RENAME TO %s',
                quoted_identifier(cr, old_name),
                quoted_identifier(cr, new_name),
            ))
        except psycopg2.Error as e:
            e.add_note(f"Renaming {old_name} to {new_name}")
            raise
        _logger.info("RENAME DB: %s -> %s", old_name, new_name)

    old_fs = odoo.tools.config.filestore(old_name)
    new_fs = odoo.tools.config.filestore(new_name)
    if os.path.exists(old_fs) and not os.path.exists(new_fs):
        shutil.move(old_fs, new_fs)

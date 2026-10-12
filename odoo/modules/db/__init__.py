# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Database management of the modules: the queries, the initialization and the management of the databases. The names are re-exported here."""

from .queries import DB_NAME_RE, DatabaseExists, FunctionStatus, _check_faketime_mode, exist, has_trigram, has_unaccent, is_initialized, list_dbs, verify_admin_password, verify_db_management_enabled
from .init import RANDOM_SERIAL, _initialize_db, country_timezones, create_categories, initialize
from .manage import _create_empty_database, _drop_conn, _dump_db_manifest, create, drop, dump, duplicate, rename, restore

__all__ = [
    'DB_NAME_RE',
    'DatabaseExists',
    'FunctionStatus',
    'RANDOM_SERIAL',
    'country_timezones',
    'create',
    'create_categories',
    'drop',
    'dump',
    'duplicate',
    'exist',
    'has_trigram',
    'has_unaccent',
    'initialize',
    'is_initialized',
    'list_dbs',
    'rename',
    'restore',
    'verify_admin_password',
    'verify_db_management_enabled',
]

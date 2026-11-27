"""Signaling of the registry between the processes: the sequences, the changes and the cursors."""

from __future__ import annotations

import threading
import time
import typing
import psycopg2.sql
from odoo.tools import SQL
from odoo.tools.lru import LRU

if typing.TYPE_CHECKING:
    from collections.abc import Collection
    from odoo.orm.database.sql_db import BaseCursor

from .base import _CACHES_BY_KEY, _REGISTRY_CACHES, _REPLICA_RETRY_TIME, _logger

def setup_signaling(self) -> None:
    """ Setup the inter-process signaling on this registry. """
    assert self.registry_sequence < 0 and not self.registry_caches__, "Setup signaling already performed"
    with self.cursor() as cr:
        # The `orm_signaling_registry` sequence indicates when the registry
        # must be reloaded.
        # The `orm_signaling_...` sequences indicates when caches must
        # be invalidated (i.e. cleared).
        signaling_tables = tuple(f'orm_signaling_{cache_name}' for cache_name in ['registry', *_CACHES_BY_KEY])
        cr.execute("SELECT table_name FROM information_schema.tables"
                   " WHERE table_name IN %s AND table_schema = current_schema", [signaling_tables])

        existing_sig_tables = tuple(s[0] for s in cr.fetchall())  # could be a set but not efficient with such a little list
        # signaling was previously using sequence but this doesn't work with replication
        # https://www.postgresql.org/docs/current/logical-replication-restrictions.html
        # this is the reason why insert only tables are used.
        for table_name in signaling_tables:
            if table_name not in existing_sig_tables:
                cr.execute(SQL(
                    "CREATE TABLE %s (id SERIAL PRIMARY KEY, date TIMESTAMP DEFAULT now())",
                    SQL.identifier(table_name),
                ))
                cr.execute(SQL("INSERT INTO %s DEFAULT VALUES", SQL.identifier(table_name)))

        db_registry_sequence, db_cache_sequences = self.get_sequences(cr)
        self.registry_sequence = db_registry_sequence
        self.registry_caches__ = {
            name: (db_cache_sequences.get(name) or 0, LRU(cache_size))
            for name, cache_size in _REGISTRY_CACHES.items()
        }

        _logger.debug("Multiprocess load registry signaling: [Registry: %s] %s",
                      db_registry_sequence, ' '.join('[Cache %s: %s]' % cs for cs in db_cache_sequences.items()))


def get_sequences(self, cr: BaseCursor) -> tuple[int, dict[str, int]]:
    signaling_tables = tuple(f'orm_signaling_{cache_name}' for cache_name in ['registry', *_CACHES_BY_KEY])
    signaling_selects = SQL(', ').join([SQL('( SELECT max(id) FROM %s)', SQL.identifier(signaling_table)) for signaling_table in signaling_tables])
    cr.execute(SQL("SELECT (now() AT TIME ZONE 'UTC'), %s", signaling_selects))
    row = cr.fetchone()
    assert row is not None, "No result when reading signaling sequences"
    now, registry_sequence, *cache_sequences_values = row
    cache_sequences = dict(zip(_CACHES_BY_KEY, cache_sequences_values))
    if cr._now is None:
        cr._now = now
    return registry_sequence, cache_sequences


def _signal_changes(self, cr: BaseCursor, names: Collection[str]) -> None:
    """ Notifies other processes if registry or cache has been invalidated. """
    if not names:
        return
    if 'registry' in names:
        _logger.info("Registry changed, signaling through the database")
        cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")
        # If another process concurrently updates the registry, the sequence
        # will actually be out-of-date, and the next call to
        # _check_signaling() will detect that and trigger a registry reload.
        return

    names = sorted(names)
    _logger.info("Caches invalidated, signaling through the database: %s", names)
    # If another process concurrently updates the cache, the sequences
    # will actually be out-of-date, and the next call to
    # _check_signaling() will detect use the new sequence.
    for cache_name in names:
        cr.execute(SQL("INSERT INTO %s DEFAULT VALUES", SQL.identifier(f'orm_signaling_{cache_name}')))


def cursor(self, /, readonly: bool = False) -> BaseCursor:
    """ Return a new cursor for the database. The cursor itself may be used
        as a context manager to commit/rollback and close automatically.

        :param readonly: Attempt to acquire a cursor on a replica database.
            Acquire a read/write cursor on the primary database in case no
            replica exists or that no readonly cursor could be acquired.
    """
    if readonly and self._db_readonly is not None:
        if (
            self._db_readonly_failed_time is None
            or time.monotonic() > self._db_readonly_failed_time + _REPLICA_RETRY_TIME
        ):
            try:
                cr = self._db_readonly.cursor()
                self._db_readonly_failed_time = None
                return cr
            except psycopg2.OperationalError:
                self._db_readonly_failed_time = time.monotonic()
                _logger.warning("Failed to open a readonly cursor, falling back to read-write cursor for %dmin %dsec", *divmod(_REPLICA_RETRY_TIME, 60))
        threading.current_thread().cursor_mode = 'ro->rw'
    return self._db.cursor()

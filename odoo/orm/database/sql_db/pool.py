"""Connections and pool of connections to the database."""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
import typing
import warnings
import psycopg2
import psycopg2.errorcodes  # noqa: F401
import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ
from psycopg2.pool import PoolError
from werkzeug import urls
import odoo
from odoo import tools
from odoo.release import MIN_PG_VERSION
from odoo.tools import config
from odoo.tools.func import locked

if typing.TYPE_CHECKING:

    # when type checking, the Cursor exposes methods of the psycopg cursor
    _CursorProtocol = psycopg2.extensions.cursor
else:
    _CursorProtocol = object

from .cursor import Cursor
from .types import PsycoConnection

_logger = logging.getLogger('odoo.sql_db')


_logger_conn = _logger.getChild("connection")


MAX_IDLE_TIMEOUT = int(os.getenv("ODOO_DB_MAX_IDLE_TIMEOUT", "600"))


class ConnectionPool:
    """ The pool of connections to database(s)

        Keep a set of connections to pg databases open, and reuse them
        to open cursors for all transactions.

        The connections are *not* automatically closed. Only a close_db()
        can trigger that.
    """

    def __init__(self, maxconn: int = 64, readonly: bool = False):
        # most recently used connections are at the end of the queue
        self._free_connections: list[PsycoConnection] = []
        self._used_connections = tools.OrderedSet[PsycoConnection]()
        self._check_free_at: float = 0.0
        self._maxconn = max(maxconn, 1)
        self._readonly = readonly
        self._lock = threading.Lock()

    def __repr__(self):
        used = len(self._used_connections)
        count = used + len(self._free_connections)
        mode = 'read-only' if self._readonly else 'read/write'
        return f"ConnectionPool({mode};used={used}/count={count}/max={self._maxconn})"

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _debug(self, msg: str, *args):
        _logger_conn.debug(('%r ' + msg), self, *args)

    @locked
    def borrow(self, connection_info: dict) -> PsycoConnection:
        """
        Borrow a PsycoConnection from the pool. If no connection is available, create a new one
        as long as there are still slots available. Perform some garbage-collection in the pool:
        idle and dead connections are removed.

        :param dict connection_info: dict of psql connection keywords
        :rtype: PsycoConnection
        """
        # find a connection, free idle and dead connections
        now = time.time()
        if (check_all := self._check_free_at < now):
            self._check_free_at = now + MAX_IDLE_TIMEOUT / 10
        close_used_before = now - MAX_IDLE_TIMEOUT
        selected_cnx = None
        for i, cnx in tools.reverse_enumerate(self._free_connections):
            if not cnx.closed and cnx._pool_last_used < close_used_before:
                self._debug('Close connection at index %d: %r', i, cnx.dsn)
                cnx.close()
            if cnx.closed:
                self._free_connections.pop(i)
                self._debug('Removing closed connection at index %d: %r', i, cnx.dsn)
            elif selected_cnx is None and self._dsn_equals(cnx.dsn, connection_info):
                self._debug('Borrow existing connection to %r at index %d', cnx.dsn, i)
                self._free_connections.pop(i)
                self._used_connections.add(cnx)
                if not check_all:
                    return cnx
                selected_cnx = cnx
        if selected_cnx is not None:
            return selected_cnx

        if len(self._free_connections) + len(self._used_connections) >= self._maxconn:
            # pool is full, try to close the oldest connection
            if self._free_connections:
                cnx = self._free_connections.pop(0)
                cnx.close()
                self._debug('Removing old connection at index %d: %r', 0, cnx.dsn)
            else:
                raise PoolError('The Connection Pool Is Full')

        try:
            result = psycopg2.connect(
                connection_factory=PsycoConnection,
                **connection_info)
            result.give_back = functools.partial(self.give_back, result)
        except psycopg2.Error:
            _logger.info('Connection to the database failed')
            raise
        if result.server_version < MIN_PG_VERSION * 10000:
            warnings.warn(f"Postgres version is {result.server_version}, lower than minimum required {MIN_PG_VERSION * 10000}")
        self._used_connections.add(result)
        self._debug('Create new connection backend PID %d', result.get_backend_pid())

        return result

    @locked
    def give_back(self, connection: PsycoConnection, keep_in_pool: bool = True):
        self._debug('Give back connection to %r', connection.dsn)
        try:
            self._used_connections.remove(connection)
        except KeyError:
            if connection in self._free_connections:
                raise PoolError("Closing a free connection")
            raise PoolError('This connection does not belong to the pool')

        if keep_in_pool and not connection.closed:
            # Release the connection and record the last time used
            self._debug('Put connection to %r in pool', connection.dsn)
            try:
                connection.reset()
            except psycopg2.OperationalError as e:
                self._debug('Cannot reset connection: %r (%s)', connection.dsn, e)
            else:
                connection._pool_last_used = time.time()
                self._free_connections.append(connection)
                return
        self._debug('Forget connection to %r', connection.dsn)
        connection.close()

    @locked
    def close_all(self, dsn: dict | str | None = None):
        count = 0
        last = None
        for i, cnx in tools.reverse_enumerate(self._free_connections):
            if dsn is None or self._dsn_equals(cnx.dsn, dsn):
                cnx.close()
                last = self._free_connections.pop(i)
                count += 1
        for cnx in self._used_connections:
            if dsn is None or self._dsn_equals(cnx.dsn, dsn):
                cnx.close()
                last = cnx
                count += 1
        if count:
            _logger.info('%r: Closed %d connections %s', self, count,
                        (dsn and last and 'to %r' % last.dsn) or '')

    def _dsn_equals(self, dsn1: dict | str, dsn2: dict | str) -> bool:
        alias_keys = {'dbname': 'database'}
        ignore_keys = ['password']
        dsn1, dsn2 = ({
            alias_keys.get(key, key): str(value)
            for key, value in (psycopg2.extensions.parse_dsn(dsn) if isinstance(dsn, str) else dsn).items()
            if key not in ignore_keys
        } for dsn in (dsn1, dsn2))
        return dsn1 == dsn2


class Connection:
    """ A lightweight instance of a connection to postgres
    """
    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
        self.__dbname = dbname
        self.__dsn = dsn
        self.__pool = pool

    @property
    def dsn(self) -> dict:
        dsn = dict(self.__dsn)
        dsn.pop('password', None)
        return dsn

    @property
    def dbname(self) -> str:
        return self.__dbname

    def cursor(self) -> Cursor:
        _logger.debug('create cursor to %r', self.dsn)
        cnx = self.__pool.borrow(self.__dsn)
        cnx.set_session(
            # See the docstring of this class.
            isolation_level=ISOLATION_LEVEL_REPEATABLE_READ,
            readonly=self.__pool.readonly,
            autocommit=False,
        )
        return Cursor(cnx, self.__dbname)

    def __bool__(self):
        raise NotImplementedError()


def connection_info_for(db_or_uri: str, readonly=False) -> tuple[str, dict]:
    """ parse the given `db_or_uri` and return a 2-tuple (dbname, connection_params)

    Connection params are either a dictionary with a single key ``dsn``
    containing a connection URI, or a dictionary containing connection
    parameter keywords which psycopg2 can build a key/value connection string
    (dsn) from

    :param str db_or_uri: database name or postgres dsn
    :param bool readonly: used to load
        the default configuration from ``db_`` or ``db_replica_``.
    :rtype: (str, dict)
    """
    app_name = config['db_app_name']
    # Using manual string interpolation for security reason and trimming at default NAMEDATALEN=63
    app_name = app_name.replace('{pid}', str(os.getpid()))[:63]
    if db_or_uri.startswith(('postgresql://', 'postgres://')):
        # extract db from uri
        us = urls.url_parse(db_or_uri)  # type: ignore
        if len(us.path) > 1:
            db_name = us.path[1:]
        elif us.username:
            db_name = us.username
        else:
            db_name = us.hostname
        return db_name, {'dsn': db_or_uri, 'application_name': app_name}

    connection_info = {'database': db_or_uri, 'application_name': app_name}
    for p in ('host', 'port', 'user', 'password', 'sslmode'):
        cfg = tools.config['db_' + p]
        if readonly:
            cfg = tools.config.get('db_replica_' + p) or cfg
        if cfg:
            connection_info[p] = cfg

    return db_or_uri, connection_info


_Pool: ConnectionPool | None = None


_Pool_readonly: ConnectionPool | None = None


def db_connect(to: str, allow_uri=False, readonly=False) -> Connection:
    global _Pool, _Pool_readonly  # noqa: PLW0603 (global-statement)

    maxconn = (tools.config['db_maxconn_gevent'] if hasattr(odoo, 'evented') and odoo.evented else 0) or tools.config['db_maxconn']
    if readonly:
        if _Pool_readonly is None:
            _Pool_readonly = ConnectionPool(int(maxconn), readonly=True)
        pool = _Pool_readonly
    else:
        if _Pool is None:
            _Pool = ConnectionPool(int(maxconn), readonly=False)
        pool = _Pool

    db, info = connection_info_for(to, readonly)
    if not allow_uri and db != to:
        raise ValueError('URI connections not allowed')
    return Connection(pool, db, info)


def close_db(db_name: str) -> None:
    """ You might want to call odoo.modules.registry.Registry.delete(db_name) along this function."""
    if _Pool:
        _Pool.close_all(connection_info_for(db_name)[1])
    if _Pool_readonly:
        _Pool_readonly.close_all(connection_info_for(db_name, readonly=True)[1])


def close_all() -> None:
    if _Pool:
        _Pool.close_all()
    if _Pool_readonly:
        _Pool_readonly.close_all()

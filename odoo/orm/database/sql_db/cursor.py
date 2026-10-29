"""Cursors of the database: the queries, the savepoints and their flushing."""

from __future__ import annotations

import logging
import os
import re
import threading
import typing
import uuid
import warnings
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from inspect import currentframe
import psycopg2
import psycopg2.errorcodes  # noqa: F401
import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras
from psycopg2 import sql as psql
from odoo import tools
from odoo.tools import SQL, config
from odoo.tools.constants import IN_MAX as IN_MAX_CONST
from odoo.tools.func import frame_codeinfo
from odoo.tools.misc import Callbacks, real_time

if typing.TYPE_CHECKING:
    from odoo.orm.models.environments import Transaction

    # when type checking, the Cursor exposes methods of the psycopg cursor
    _CursorProtocol = psycopg2.extensions.cursor
else:
    _CursorProtocol = object

from .types import PsycoConnection

try:
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import PostgresLexer

    def highlight_sql(sql_query: str) -> str:
        """
        Applies ANSI syntax highlighting to a SQL string for terminal output.

        Enable it via the ~/.odoorc (-c/--config) configuration file::

            [colors]
            sql = auto
        """
        return highlight(sql_query, PostgresLexer(), TerminalFormatter()).strip()
except ImportError:
    def highlight_sql(sql_query: str) -> str:
        warnings.warn("Pygments needs to be installed in order to highlight SQL")
        return sql_query


_logger = logging.getLogger('odoo.sql_db')


re_from = re.compile(r'\bfrom\s+"?([a-zA-Z_0-9]+)\b', re.IGNORECASE)


re_into = re.compile(r'\binto\s+"?([a-zA-Z_0-9]+)\b', re.IGNORECASE)


PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = (
    psycopg2.errors.LockNotAvailable,
    psycopg2.errors.SerializationFailure,
    psycopg2.errors.DeadlockDetected,
)


def categorize_query(decoded_query: str) -> tuple[typing.Literal['from', 'into'], str] | tuple[typing.Literal['other'], None]:
    res_into = re_into.search(decoded_query)
    # prioritize `insert` over `select` so `select` subqueries are not
    # considered when inside a `insert`
    if res_into:
        return 'into', res_into.group(1)

    res_from = re_from.search(decoded_query)
    if res_from:
        return 'from', res_from.group(1)

    return 'other', None


sql_counter: int = 0


class Savepoint:
    """ Reifies an active breakpoint, allows :meth:`Cursor.savepoint` users
    to internally rollback the savepoint (as many times as they want) without
    having to implement their own savepointing, or triggering exceptions.

    Should normally be created using :meth:`Cursor.savepoint` rather than
    directly.

    The savepoint will be rolled back on unsuccessful context exits
    (exceptions). It will be released ("committed") on successful context exit.
    The savepoint object can be wrapped in ``contextlib.closing`` to
    unconditionally roll it back.

    The savepoint can also safely be explicitly closed during context body. This
    will rollback by default.

    :param Cursor cr: the cursor to execute the `SAVEPOINT` queries on
    """

    def __init__(self, cr: _CursorProtocol):
        self.name = str(uuid.uuid1())
        self._cr = cr
        self.closed: bool = False
        cr.execute(psql.SQL('SAVEPOINT {}').format(psql.Identifier(self.name)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close(rollback=exc_type is not None)

    def close(self, *, rollback: bool = True):
        if not self.closed:
            self._close(rollback)

    def rollback(self):
        self._cr.execute(psql.SQL('ROLLBACK TO SAVEPOINT {}').format(psql.Identifier(self.name)))

    def _close(self, rollback: bool):
        if rollback:
            self.rollback()
        self._cr.execute(psql.SQL('RELEASE SAVEPOINT {}').format(psql.Identifier(self.name)))
        self.closed = True


class _FlushingSavepoint(Savepoint):
    def __init__(self, cr: Cursor):
        cr.flush()
        if cr.transaction is not None:
            cr.transaction.save_state()
        super().__init__(cr)

    def rollback(self):
        cr = self._cr
        assert isinstance(cr, Cursor)
        super().rollback()
        cr.precommit.clear()  # they were flushed in the init
        if cr.transaction is not None:
            cr.transaction.restore_state()

    def _close(self, rollback: bool):
        cr = self._cr
        assert isinstance(cr, Cursor)
        try:
            if not rollback:
                cr.flush()
        except Exception:
            rollback = True
            raise
        finally:
            super()._close(rollback)
            if cr.transaction is not None:
                cr.transaction.merge_state()


class Cursor(_CursorProtocol):
    """Represents an open transaction to the PostgreSQL DB backend,
       acting as a lightweight wrapper around psycopg2's
       ``cursor`` objects.

        ``Cursor`` is the object behind the ``cr`` variable used all
        over the OpenERP code.

        .. rubric:: Transaction Isolation

        One very important property of database transactions is the
        level of isolation between concurrent transactions.
        The SQL standard defines four levels of transaction isolation,
        ranging from the most strict *Serializable* level, to the least
        strict *Read Uncommitted* level. These levels are defined in
        terms of the phenomena that must not occur between concurrent
        transactions, such as *dirty read*, etc.
        In the context of a generic business data management software
        such as OpenERP, we need the best guarantees that no data
        corruption can ever be cause by simply running multiple
        transactions in parallel. Therefore, the preferred level would
        be the *serializable* level, which ensures that a set of
        transactions is guaranteed to produce the same effect as
        running them one at a time in some order.

        However, most database management systems implement a limited
        serializable isolation in the form of
        `snapshot isolation <http://en.wikipedia.org/wiki/Snapshot_isolation>`_,
        providing most of the same advantages as True Serializability,
        with a fraction of the performance cost.
        With PostgreSQL up to version 9.0, this snapshot isolation was
        the implementation of both the ``REPEATABLE READ`` and
        ``SERIALIZABLE`` levels of the SQL standard.
        As of PostgreSQL 9.1, the previous snapshot isolation implementation
        was kept for ``REPEATABLE READ``, while a new ``SERIALIZABLE``
        level was introduced, providing some additional heuristics to
        detect a concurrent update by parallel transactions, and forcing
        one of them to rollback.

        OpenERP implements its own level of locking protection
        for transactions that are highly likely to provoke concurrent
        updates, such as stock reservations or document sequences updates.
        Therefore we mostly care about the properties of snapshot isolation,
        but we don't really need additional heuristics to trigger transaction
        rollbacks, as we are taking care of triggering instant rollbacks
        ourselves when it matters (and we can save the additional performance
        hit of these heuristics).

        As a result of the above, we have selected ``REPEATABLE READ`` as
        the default transaction isolation level for OpenERP cursors, as
        it will be mapped to the desired ``snapshot isolation`` level for
        all supported PostgreSQL version (>10).

        .. attribute:: cache

            Cache dictionary with a "request" (-ish) lifecycle, only lives as
            long as the cursor itself does and proactively cleared when the
            cursor is closed.

            This cache should *only* be used to store repeatable reads as it
            ignores rollbacks and savepoints, it should not be used to store
            *any* data which may be modified during the life of the cursor.

    """
    IN_MAX = IN_MAX_CONST   # decent limit on size of IN queries - guideline = Oracle limit

    def __init__(self, cnx: PsycoConnection, dbname: str):
        super().__init__()
        self.precommit = Callbacks()
        self.postcommit = Callbacks()
        self.prerollback = Callbacks()
        self.postrollback = Callbacks()
        self._now: datetime | None = None
        self.cache: dict[typing.Any, typing.Any] = {}

        # By default a cursor has no transaction object.  A transaction object
        # for managing environments is instantiated by registry.cursor().  It
        # is not done here in order to avoid cyclic module dependencies.
        self.transaction: Transaction | None = None

        self.sql_from_log: dict[str, tuple[int, float]] = {}
        self.sql_into_log: dict[str, tuple[int, float]] = {}

        # default log level determined at cursor creation, could be
        # overridden later for debugging purposes
        self.sql_log_count: int = 0

        # avoid the call of close() (by __del__) if an exception
        # is raised by any of the following initializations
        self._closed: bool = True
        self._closing: bool = False

        self.dbname = dbname
        self._cnx = cnx
        self._obj: psycopg2.extensions.cursor = cnx.cursor()
        if _logger.isEnabledFor(logging.DEBUG):
            self.__caller: tuple[str, str | int] | None = frame_codeinfo(currentframe(), 2)
        else:
            self.__caller = None
        self._closed = False   # real initialization value

        if os.getenv('ODOO_FAKETIME_TEST_MODE') and self.dbname in tools.config['db_name']:
            self._obj.execute("SET SESSION search_path = public, pg_catalog;")
            self._cnx.commit()  # ensure that the search_path remains after a rollback

    def flush(self) -> None:
        """ Flush the current transaction, and run precommit hooks. """
        # In case some pre-commit added another pre-commit or triggered changes
        # in the ORM, we must flush and run it again.
        for _ in range(10):  # limit number of iterations
            if self.transaction is not None:
                self.transaction.flush()
            if not self.precommit:
                break
            self.precommit.run()
        else:
            _logger.warning("Too many iterations for flushing the cursor!")

    def savepoint(self, flush: bool = True) -> Savepoint:
        """context manager entering in a new savepoint

        With ``flush`` (the default), will automatically run (or clear) the
        relevant hooks.
        """
        if flush:
            return _FlushingSavepoint(self)
        else:
            return Savepoint(self)

    def __enter__(self):
        """ Using the cursor as a contextmanager automatically commits and
            closes it::

                with cr:
                    cr.execute(...)

                # cr is committed if no failure occurred
                # cr is closed in any case
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._closing = True
        try:
            if exc_type is None and not self.closed:
                self.commit()
        finally:
            self.close()

    def now(self) -> datetime:
        """ Return the transaction's timestamp ``NOW() AT TIME ZONE 'UTC'``. """
        if self._now is None:
            self.execute("SELECT (now() AT TIME ZONE 'UTC')")
            row = self.fetchone()
            assert row
            self._now = row[0]
        return self._now

    def dictfetchone(self) -> dict[str, typing.Any] | None:
        """ Return the first row as a dict (column_name -> value) or None if no rows are available. """
        description = self._obj.description
        assert description, "Query does not have results"
        row = self._obj.fetchone()
        return {column.name: value for column, value in zip(description, row)} if row else None

    def dictfetchmany(self, size) -> list[dict[str, typing.Any]]:
        description = self._obj.description
        assert description, "Query does not have results"
        names = [column.name for column in description]
        return [dict(zip(names, row)) for row in self._obj.fetchmany(size)]

    def dictfetchall(self) -> list[dict[str, typing.Any]]:
        """ Return all rows as dicts (column_name -> value). """
        description = self._obj.description
        assert description, "Query does not have results"
        names = [column.name for column in description]
        return [dict(zip(names, row)) for row in self._obj.fetchall()]

    def __del__(self):
        if not self._closed:
            # Oops. 'self' has not been closed explicitly.
            # The cursor will be deleted by the garbage collector,
            # but the database connection is not put back into the connection
            # pool, preventing some operation on the database like dropping it.
            # This can also lead to a server overload.
            msg = "Cursor not closed explicitly\n"
            if self.__caller:
                msg += "Cursor was created at %s:%s" % self.__caller
            else:
                msg += "Please enable sql debugging to trace the caller."
            _logger.log(logging.DEBUG if self._cnx.closed else logging.WARNING, msg)
            # Just close the raw connection as other all environments are
            # (being) collected at this time.
            self._cnx.give_back(keep_in_pool=False)

    def _format(self, query, params=None, /, color_highlight=True) -> str:
        encoding = psycopg2.extensions.encodings[self.connection.encoding]
        formatted = self.mogrify(query, params).decode(encoding, 'replace')
        if color_highlight and config.colors['sql']:
            return highlight_sql(formatted)
        return formatted

    def mogrify(self, query: SQL | typing.LiteralString | psql.Composable, params=None) -> bytes:
        if isinstance(query, SQL):
            assert params is None, "Unexpected parameters for SQL query object"
            query, params, _fields = query._sql_tuple
        return self._obj.mogrify(query, params)

    def execute(self, query: SQL | typing.LiteralString | psql.Composable, params=None, log_exceptions: bool = True) -> None:
        """ Execute a query inside the current transaction. """
        global sql_counter

        if isinstance(query, SQL):
            assert params is None, "Unexpected parameters for SQL query object"
            query, params, _fields = query._sql_tuple
        elif params and not isinstance(params, (tuple, list, dict)):
            # psycopg2's TypeError is not clear if you mess up the params
            raise ValueError(f"SQL query parameters should be a tuple, list or dict; got {params!r}")

        start = real_time()
        update_query_endtime_functions = []
        current_thread = threading.current_thread()
        for hook in getattr(current_thread, 'query_hooks', ()):
            func = hook(self, query, params, start, 10)
            if func and callable(func):
                update_query_endtime_functions.append(func)

        try:
            self._obj.execute(query, params)
        except Exception as e:
            if log_exceptions:
                _logger.error("bad query: %s\nERROR: %s", self._obj.query or query, e)
            raise
        finally:
            delay = real_time() - start
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug("[%.3f ms] query: %s", 1000 * delay, self._format(query, params))
            # optional hooks for performance and tracing analysis
            for update_query_endtime_function in update_query_endtime_functions:
                update_query_endtime_function(delay)

        # simple query count is always computed
        self.sql_log_count += 1
        sql_counter += 1

        if hasattr(current_thread, 'query_count'):
            current_thread.query_count += 1
        if hasattr(current_thread, 'query_time'):
            current_thread.query_time += delay

        # advanced stats
        if _logger.isEnabledFor(logging.DEBUG):
            if obj_query := self._obj.query:
                query = obj_query.decode()
            query_type, table = categorize_query(query)
            log_target = None
            if query_type == 'into':
                log_target = self.sql_into_log
            elif query_type == 'from':
                log_target = self.sql_from_log
            if log_target:
                stat_count, stat_time = log_target.get(table or '', (0, 0))
                log_target[table or ''] = (stat_count + 1, stat_time + delay * 1E6)

    def executemany(self, query: typing.LiteralString | psql.Composable, vars_list) -> None:
        """Execute the query for each row in the vars_list."""
        for params in vars_list:
            self.execute(query, params)

    def execute_values(self, query: typing.LiteralString | psql.Composable, argslist, template=None, page_size=100, fetch=False):
        """
        A proxy for psycopg2.extras.execute_values which can log all queries like execute.
        But this method cannot set log_exceptions=False like execute
        """
        # Odoo Cursor only proxies all methods of psycopg2 Cursor. This is a patch for problems caused by passing
        # self instead of self._obj to the first parameter of psycopg2.extras.execute_values.
        if isinstance(query, psql.Composable):
            query = query.as_string(self._obj)
        return psycopg2.extras.execute_values(self, query, argslist, template=template, page_size=page_size, fetch=fetch)

    def print_log(self) -> None:
        global sql_counter

        def process(log_type: str):
            sqllogs = {'from': self.sql_from_log, 'into': self.sql_into_log}
            sqllog = sqllogs[log_type]
            total = 0.0
            if sqllog:
                _logger.debug("SQL LOG %s:", log_type)
                for table, (stat_count, stat_time) in sorted(sqllog.items(), key=lambda k: k[1]):
                    delay = timedelta(microseconds=stat_time)
                    _logger.debug("table: %s: %s/%s", table, delay, stat_count)
                    total += stat_time
                sqllog.clear()
            total_delay = timedelta(microseconds=total)
            _logger.debug("SUM %s:%s/%d [%d]", log_type, total_delay, self.sql_log_count, sql_counter)

        process('from')
        process('into')

    @contextmanager
    def _enable_logging(self):
        """ Forcefully enables logging for this cursor, restores it afterwards.

        Updates the logger in-place, so not thread-safe.
        """
        level = _logger.level
        _logger.setLevel(logging.DEBUG)
        try:
            yield
        finally:
            _logger.setLevel(level)

    def close(self) -> None:
        self._closing = True
        if self._closed:
            return

        # Clean the underlying connection, and run rollback hooks and business
        # logic.
        try:
            self.rollback()

        except psycopg2.InterfaceError:
            # mask 'connection already closed' error
            if not self._cnx.closed:
                raise

        finally:
            # Close even if we had failures during rollback
            if not self._closed:
                self._close()

    def _close(self) -> None:
        # The connection may have been closed, so give it back in finally block.
        assert not self._closed, "Connection already closed"
        self._closed = True

        # Advanced stats only at logging.DEBUG level
        if _logger.isEnabledFor(logging.DEBUG):
            self.print_log()

        # This force the cursor to be freed, and thus, available again. It is
        # important because otherwise we can overload the server very easily
        # because of a cursor shortage (because cursors are not garbage
        # collected as fast as they should). The problem is probably due in
        # part because browse records keep a reference to the cursor.
        self._obj.close()
        del self._obj

        # Put the connection back to the pool
        # Forget already closed connections and system-related databases
        keep_in_pool = not self._cnx.closed and self.dbname not in (
            'template0', 'template1',
            # keep open if one of preloaded databases
            config['db_system'] if config['db_system'] not in config['db_name'] else '',
            config['db_template'],
        )
        self._cnx.give_back(keep_in_pool=keep_in_pool)

        if self.transaction is not None:
            self.transaction._free_resources()
        self.cache.clear()

    def commit(self) -> None:
        """ Commit the current transaction. """
        self.flush()
        committing = self.transaction.committing() if self.transaction is not None else nullcontext()
        with committing:
            self._cnx.commit()
            self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        if self._closing:
            self._close()
        self.postcommit.run()

    def rollback(self) -> None:
        """ Rollback the current transaction. """
        self.precommit.clear()
        self.postcommit.clear()
        try:
            self.prerollback.run()
        except Exception:
            _logger.exception("Error during prerollback execution, ignore")
            self.prerollback.clear()
        rollbacking = self.transaction.rollbacking() if self.transaction is not None else nullcontext()
        with rollbacking:
            self._cnx.rollback()
            self._now = None
        if self._closing:
            self._close()
        try:
            self.postrollback.run()
        except Exception:
            if self.closed:
                _logger.exception("Error during postrollback execution, cursor closed")
                return
            _logger.exception("Error during postrollback execution, rollback again")
            # make sure there are no more hooks and retry
            self.prerollback.clear()
            self.postrollback.clear()
            self.rollback()

    def __getattr__(self, name):
        if self._closed and name == '_obj':
            raise psycopg2.InterfaceError("Cursor already closed")
        return getattr(self._obj, name)

    @property
    def closed(self) -> bool:
        return self._closed or bool(self._cnx.closed)

    @property
    def readonly(self) -> bool:
        return bool(self._cnx.readonly)


BaseCursor = Cursor  # backward-compatibility

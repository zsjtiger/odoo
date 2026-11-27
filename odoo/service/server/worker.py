# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Workers of the prefork server: the HTTP and cron worker processes."""

import errno
import logging
import os
import random
import select
import signal
import socket
import threading
import time
import contextvars
from collections import deque

import psutil

from odoo.http.server import HTTPSocket
from odoo.modules.registry import Registry
from odoo.orm.database import sql_db
from odoo.tools import OrderedSet, config
from odoo.tools.system.osutil import memory_info

from .common import SLEEP_INTERVAL, cron_database_list, empty_pipe, pipe_new, pipe_ping, set_limit_memory_hard

if os.name == 'posix':
    # Unix only for workers
    import fcntl
    import resource

# Optional process names for workers
try:
    from setproctitle import setproctitle
except ImportError:
    def setproctitle(x):
        return None


_logger = logging.getLogger('odoo.service.server')


class Worker:
    """ Workers """
    def __init__(self, multi):
        self.multi = multi
        self.watchdog_time = time.time()
        self.watchdog_pipe = pipe_new()
        self.eintr_pipe = pipe_new()
        self.wakeup_fd_r, self.wakeup_fd_w = self.eintr_pipe
        # Can be set to None if no watchdog is desired.
        self.watchdog_timeout = multi.timeout
        self.ppid = os.getpid()
        self.pid = None
        self.alive = True
        # should we rename into lifetime ?
        self.request_max = multi.limit_request
        self.request_count = 0
        self.logger = _logger.getChild(self.__class__.__name__)

    def setproctitle(self, title=""):
        setproctitle('odoo: %s %s %s' % (self.__class__.__name__, self.pid, title))

    def close(self):
        os.close(self.watchdog_pipe[0])
        os.close(self.watchdog_pipe[1])
        os.close(self.eintr_pipe[0])
        os.close(self.eintr_pipe[1])

    def signal_handler(self, sig, frame):
        self.alive = False

    def signal_time_expired_handler(self, n, stack):
        # TODO: print actual RUSAGE_SELF (since last check_limits) instead of
        #       just repeating the config setting
        self.logger.info("CPU time limit (%s) reached.", config['limit_time_cpu'])
        # We dont suicide in such case
        msg = "CPU time limit exceeded."
        raise Exception(msg)  # noqa: TRY002

    def sleep(self):
        try:
            select.select([self.multi.socket, self.wakeup_fd_r], [], [], self.multi.beat)
            # clear wakeup pipe if we were interrupted
            empty_pipe(self.wakeup_fd_r)
        except OSError as e:
            if e.args[0] not in [errno.EINTR]:
                raise

    def check_limits(self):
        # If our parent changed suicide
        if self.ppid != os.getppid():
            self.logger.info("Parent changed")
            self.alive = False
        # check for lifetime
        if self.request_count >= self.request_max:
            self.logger.info("Max request (%s) reached.", self.request_count)
            self.alive = False
        # Reset the worker if it consumes too much memory (e.g. caused by a memory leak).
        memory = memory_info(psutil.Process(os.getpid()))  # TODO: optimize this line
        if config['limit_memory_soft'] and memory > config['limit_memory_soft']:
            self.logger.info("Virtual memory limit (%s) reached.", memory)
            self.alive = False      # Commit suicide after the request.

        set_limit_memory_hard()

        # update RLIMIT_CPU so limit_time_cpu applies per unit of work
        r = resource.getrusage(resource.RUSAGE_SELF)
        cpu_time = r.ru_utime + r.ru_stime
        _soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_time + config['limit_time_cpu']), hard))

    def process_work(self):
        pass

    def start(self):
        self.pid = os.getpid()
        self.setproctitle()
        self.logger.info("Alive")
        # Reseed the random number generator
        random.seed()
        if self.multi.socket:
            # Prevent fd inheritance: close_on_exec
            flags = fcntl.fcntl(self.multi.socket, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
            fcntl.fcntl(self.multi.socket, fcntl.F_SETFD, flags)
            # reset blocking status
            self.multi.socket.setblocking(0)

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGXCPU, self.signal_time_expired_handler)

        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGTTIN, signal.SIG_DFL)
        signal.signal(signal.SIGTTOU, signal.SIG_DFL)

        signal.set_wakeup_fd(self.wakeup_fd_w)

    def stop(self):
        pass

    def run(self):
        self.start()
        t = threading.Thread(
            name=f"Worker {self.__class__.__name__} ({self.pid}) workthread",
            target=self._runloop,
            daemon=True,
        )
        t.start()
        t.join()
        self.logger.info("Exiting cleanly. request_count: %s, registry count: %s.", self.request_count, len(Registry.registries))
        self.stop()

    def _runloop(self):
        signal.pthread_sigmask(signal.SIG_BLOCK, {
            signal.SIGXCPU,
            signal.SIGINT, signal.SIGQUIT,
            signal.SIGUSR1, signal.SIGUSR2,
        })
        try:
            while self.alive:
                self.check_limits()
                pipe_ping(self.watchdog_pipe)
                self.sleep()
                if not self.alive:
                    break
                self.process_work()
        except BaseException as exc:
            self.logger.exception("Exception occurred, exiting...")
            raise SystemExit(1) from exc


class WorkerHTTP(Worker):
    """ HTTP Request workers """
    def __init__(self, multi):
        super().__init__(multi)

        # The ODOO_HTTP_SOCKET_TIMEOUT environment variable allows to control socket timeout for
        # extreme latency situations. It's generally better to use a good buffering reverse proxy
        # to quickly free workers rather than increasing this timeout to accommodate high network
        # latencies & b/w saturation. This timeout is also essential to protect against accidental
        # DoS due to idle HTTP connections.
        sock_timeout = os.environ.get("ODOO_HTTP_SOCKET_TIMEOUT")
        self.sock_timeout = float(sock_timeout) if sock_timeout else 2

    def process_request(self, client, addr):
        client.setblocking(1)
        client.settimeout(self.sock_timeout)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Prevent fd inherientence close_on_exec
        flags = fcntl.fcntl(client, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(client, fcntl.F_SETFD, flags)
        http_socket = HTTPSocket(client, addr)
        http_socket.process_request()

        self.request_count += 1

    def process_work(self):
        try:
            client, addr = self.multi.socket.accept()
        except (BlockingIOError, ConnectionAbortedError):
            pass
        else:
            with client:
                contextvars.Context().run(self.process_request, client, addr)


class WorkerCron(Worker):
    """ Cron workers """

    def __init__(self, multi):
        super().__init__(multi)
        self.alive_time = time.monotonic()
        self.watchdog_timeout = multi.cron_timeout  # Use a distinct value for CRON Worker
        # process_work() below process a single database per call.
        # self.db_queue keeps track of the databases to process (in order, from left to right).
        self.db_queue: deque[str] = deque()
        self.db_count: int = 0

    def sleep(self):
        # Really sleep once all the databases have been processed.
        if not self.db_queue:
            interval = SLEEP_INTERVAL + self.pid % 10   # chorus effect

            # simulate interruptible sleep with select(wakeup_fd, timeout)
            try:
                select.select([self.wakeup_fd_r, self.dbcursor._cnx], [], [], interval)
                # clear pg_conn/wakeup pipe if we were interrupted
                time.sleep(self.pid / 100 % .1)
                self.dbcursor._cnx.poll()
                empty_pipe(self.wakeup_fd_r)
            except OSError as e:
                if e.args[0] != errno.EINTR:
                    raise

    def check_limits(self):
        super().check_limits()

        if config['limit_time_worker_cron'] > 0 and (time.monotonic() - self.alive_time) > config['limit_time_worker_cron']:
            self.logger.info("Max age (%ss) reached.", config['limit_time_worker_cron'])
            self.alive = False

    def process_work(self):
        """Process a single database."""
        self.logger.debug("polling for jobs")

        if not self.db_queue:
            # list databases
            db_names = OrderedSet(cron_database_list())
            pg_conn = self.dbcursor._cnx
            notified = OrderedSet(
                notif.payload
                for notif in pg_conn.notifies
                if notif.channel == 'cron_trigger'
            )
            pg_conn.notifies.clear()  # free resources
            # add notified databases (in order) first in the queue
            self.db_queue.extend(db for db in notified if db in db_names)
            self.db_queue.extend(db for db in db_names if db not in notified)
            self.db_count = len(self.db_queue)
            if not self.db_count:
                return

        # pop the leftmost element (because notified databases appear first)
        db_name = self.db_queue.popleft()
        self.setproctitle(db_name)

        from odoo.addons.base.models.ir_cron import IrCron  # noqa: PLC0415
        contextvars.Context().run(IrCron._process_jobs, db_name)

        # dont keep cursors in multi database mode
        if self.db_count > 1:
            sql_db.close_db(db_name)

        self.request_count += 1
        if self.request_count >= self.request_max and self.request_max < self.db_count:
            self.logger.error(
                "There are more dabatases to process than allowed "
                "by the `limit_request` configuration variable: %s more.",
                self.db_count - self.request_max,
            )

    def start(self):
        os.nice(10)     # mommy always told me to be nice with others...
        super().start()
        if self.multi.socket:
            self.multi.socket.close()
        if registries_size := os.environ.get('ODOO_REGISTRY_LRU_SIZE_CRON'):
            Registry.registries.count = int(registries_size)

        dbconn = sql_db.db_connect(config['db_system'])
        self.dbcursor = dbconn.cursor()
        # LISTEN / NOTIFY doesn't work in recovery mode
        self.dbcursor.execute("SELECT pg_is_in_recovery()")
        in_recovery = self.dbcursor.fetchone()[0]
        if not in_recovery:
            self.dbcursor.execute("LISTEN cron_trigger")
        else:
            self.logger.warning("PG cluster in recovery mode, cron trigger not activated")
        self.dbcursor.commit()

    def stop(self):
        super().stop()
        self.dbcursor._cnx.close()
        self.dbcursor.close()

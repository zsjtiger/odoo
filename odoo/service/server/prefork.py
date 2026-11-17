# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Prefork server: the supervisor of the forked HTTP and cron workers."""

import contextlib
import errno
import logging
import os
import select
import signal
import socket
import subprocess
import sys
import time
import collections

import psutil

from odoo import api
from odoo.modules.registry import Registry
from odoo.orm.database import sql_db
from odoo.orm.models.cache import log_ormcache_stats
from odoo.tools import config
from odoo.tools.misc import dumpstacks, stripped_sys_argv

from . import common
from .common import CommonServer, empty_pipe, pipe_new, pipe_ping
from .worker import WorkerCron, WorkerHTTP
from .startup import _reexec, preload_registries

if os.name == 'posix':
    # Unix only for workers
    import fcntl


_logger = logging.getLogger('odoo.service.server')


class PreforkServer(CommonServer):
    """ Multiprocessing inspired by (g)unicorn.
    PreforkServer (aka Multicorn) currently uses accept(2) as dispatching
    method between workers but we plan to replace it by a more intelligent
    dispatcher to will parse the first HTTP request line.
    """
    def __init__(self, app):
        super().__init__(app)
        # config
        self.population = config['workers']
        self.timeout = config['limit_time_real']
        self.limit_request = config['limit_request']
        self.cron_timeout = config['limit_time_real_cron'] or None
        if self.cron_timeout == -1:
            self.cron_timeout = self.timeout
        # working vars
        self.beat = 4
        self.socket = None
        self.workers_http = {}
        self.workers_cron = {}
        self.workers = {}
        self.generation = 0
        self.queue = collections.deque()
        self.servers_gevent = {}

    def signal_handler(self, sig, frame):
        if len(self.queue) < 5 or sig == signal.SIGCHLD:
            self.queue.append(sig)
            pipe_ping(self.pipe)
        else:
            self.logger.warning("Dropping signal: %s", sig)

    def worker_spawn(self, klass, workers_registry):
        self.generation += 1
        worker = klass(self)
        pid = os.fork()
        if pid != 0:
            # parent
            worker.pid = pid
            self.workers[pid] = worker
            workers_registry[pid] = worker
            return worker

        # child
        try:
            worker.run()
        except SystemExit:
            raise
        except BaseException as exc:
            self.logger.critical("Worker %s (%d): uncaught error in main loop, exiting...",
                worker.__class__.__name__, worker.pid, exc_info=exc)
            raise SystemExit(1) from exc
        exit()

    def gevent_spawn(self):
        nargs = stripped_sys_argv()
        cmd = [sys.executable, sys.argv[0], 'gevent'] + nargs[1:]
        popen = subprocess.Popen(cmd)
        self.servers_gevent[popen.pid] = popen

    def worker_pop(self, pid):
        if pid in self.servers_gevent:
            self.logger.debug("gevent worker (%s) unregistered", pid)
            self.servers_gevent.pop(pid)
        if pid in self.workers:
            self.logger.debug("worker (%s) unregistered", pid)
            try:
                self.workers_http.pop(pid, None)
                self.workers_cron.pop(pid, None)
                u = self.workers.pop(pid)
                u.close()
            except OSError:
                return

    def worker_kill(self, pid, sig):
        try:
            os.kill(pid, sig)
            if sig == signal.SIGKILL:
                self.worker_pop(pid)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self.worker_pop(pid)

    def process_signals(self):
        while self.queue:
            sig = self.queue.popleft()
            if sig in [signal.SIGINT, signal.SIGTERM]:
                raise KeyboardInterrupt
            if sig == signal.SIGHUP:
                # restart on kill -HUP
                common.server_phoenix = True
                raise KeyboardInterrupt
            if sig == signal.SIGQUIT:
                # dump stacks on kill -3
                dumpstacks()
            elif sig in [signal.SIGUSR1, signal.SIGUSR2]:
                # log ormcache stats on kill -SIGUSR1 or kill -SIGUSR2
                log_ormcache_stats(sig)
            elif sig == signal.SIGTTIN:
                # increase number of workers
                self.population += 1
            elif sig == signal.SIGTTOU:
                # decrease number of workers
                self.population -= 1

    def process_zombie(self):
        # reap dead workers
        while True:
            try:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
                if (status >> 8) == 3:
                    msg = "Worker (%s): dead"
                    self.logger.critical(msg, wpid)
                    raise Exception(msg % wpid)  # noqa: TRY002
                self.worker_pop(wpid)
            except OSError as e:
                if e.errno == errno.ECHILD:
                    break
                raise

    def process_timeout(self):
        now = time.time()
        for (pid, worker) in list(self.workers.items()):
            if worker.watchdog_timeout is not None and \
                    (now - worker.watchdog_time) >= worker.watchdog_timeout:
                self.logger.error("%s (%s) timeout after %ss",
                    worker.__class__.__name__, pid, worker.watchdog_timeout)
                self.worker_kill(pid, signal.SIGQUIT)  # dump stack
                time.sleep(0.1)
                self.worker_kill(pid, signal.SIGKILL)

    def process_spawn(self):
        # Before spawning any process, check the registry signaling
        registries = Registry.registries.snapshot

        def check_registries():
            # check the registries on the first call only!
            if not registries:
                return
            for registry in registries.values():
                try:
                    with contextlib.closing(registry.cursor()) as cr:
                        # check signaling by instantiating an environment
                        api.Environment(cr, api.SUPERUSER_ID, {})
                except Exception as e:  # noqa: BLE001
                    _logger.info("Continue spawning, failed to check signaling on %s. Cause: %s", registry.db_name, e)
            registries.clear()
            # Close all opened cursors
            sql_db.close_all()

        if config['http_enable']:
            while len(self.workers_http) < self.population:
                check_registries()
                self.worker_spawn(WorkerHTTP, self.workers_http)
            while len(self.servers_gevent) < config['gevent_workers']:
                check_registries()
                self.gevent_spawn()
        while len(self.workers_cron) < config['max_cron_threads']:
            check_registries()
            self.worker_spawn(WorkerCron, self.workers_cron)

    def sleep(self):
        try:
            # map of fd -> worker
            fds = {w.watchdog_pipe[0]: w for w in self.workers.values()}
            fd_in = list(fds) + [self.pipe[0]]
            # check for ping or internal wakeups
            ready = select.select(fd_in, [], [], self.beat)
            # update worker watchdogs
            for fd in ready[0]:
                if fd in fds:
                    fds[fd].watchdog_time = time.time()
                empty_pipe(fd)
        except OSError as e:
            # TODO: drop execept as EINTR is handled by python, see pep-0475
            if e.args[0] not in [errno.EINTR]:
                raise

    def start(self):
        # wakeup pipe, python doesn't throw EINTR when a syscall is interrupted
        # by a signal simulating a pseudo SA_RESTART. We write to a pipe in the
        # signal handler to overcome this behaviour
        self.pipe = pipe_new()
        # set signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)
        signal.signal(signal.SIGCHLD, self.signal_handler)
        signal.signal(signal.SIGTTIN, self.signal_handler)
        signal.signal(signal.SIGTTOU, self.signal_handler)
        signal.signal(signal.SIGQUIT, dumpstacks)
        signal.signal(signal.SIGUSR1, log_ormcache_stats)
        signal.signal(signal.SIGUSR2, log_ormcache_stats)

        if config['http_enable']:
            if os.environ.get('ODOO_HTTP_SOCKET_FD'):
                # reload
                self.socket = socket.socket(fileno=int(os.environ.pop('ODOO_HTTP_SOCKET_FD')))
            elif config.http_socket_activation:
                # socket activation
                SD_LISTEN_FDS_START = 3
                self.socket = socket.fromfd(SD_LISTEN_FDS_START, socket.AF_INET, socket.SOCK_STREAM)
            else:
                # default
                self.socket = socket.create_server(
                    (self.interface, self.port),
                    family=socket.AF_INET6 if ':' in self.interface else socket.AF_INET,
                    backlog=8 * self.population,
                    dualstack_ipv6=self.interface == '::',
                )
                self.socket.setblocking(0)
                if self.port == 0:
                    self.port = config['http_port'] = self.socket.getsockname()[1]

            if config.http_socket_activation:
                _logger.info("HTTP service running through socket activation")
            else:
                host, port, *_ = self.socket.getsockname()
                if host == '::':
                    host = '*'  # dual stack
                elif ':' in host:
                    host = f'[{host}]'
                _logger.info("HTTP service running on %s:%s", host, port)

    def fork_and_reload(self):
        self.logger.info("Reloading server")
        pid = os.fork()
        if pid != 0:
            # keep the http listening socket open during _reexec() to ensure uptime
            http_socket_fileno = self.socket.fileno()
            flags = fcntl.fcntl(http_socket_fileno, fcntl.F_GETFD)
            fcntl.fcntl(http_socket_fileno, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
            os.environ['ODOO_HTTP_SOCKET_FD'] = str(http_socket_fileno)
            os.environ['ODOO_READY_SIGHUP_PID'] = str(pid)

            if not hasattr(socket, 'SO_REUSEPORT'):
                # The new GeventServer won't be able to spawn if the address is in use
                for pid in list(self.servers_gevent):
                    self.worker_kill(pid, signal.SIGKILL)
            _reexec()  # stops execution

        # child process handles old server shutdown
        self.logger.info("Waiting for new server to start ...")
        phoenix_hatched = False

        def sighup_handler(sig, frame):
            nonlocal phoenix_hatched
            phoenix_hatched = True

        signal.signal(signal.SIGHUP, sighup_handler)

        start_time = time.monotonic()
        while not phoenix_hatched and time.monotonic() < start_time + 60:
            time.sleep(0.1)

        if not phoenix_hatched:
            self.logger.error("Server reload timed out (check the updated code)")
            return 0
        self.logger.info("New server has started")

        return max(time.monotonic() - start_time, 0.1)

    def stop_workers_gracefully(self, respawn_time=0):
        self.logger.info("Stopping workers gracefully")

        # Signal workers to finish their current workload then stop
        for pid in self.workers:
            self.worker_kill(pid, signal.SIGINT)

        is_main_server = self.pid == os.getpid()  # False if server reload, cannot reap children -> use psutil
        if not is_main_server:
            processes = {}
            for pid in list(self.workers) + list(self.servers_gevent):
                try:
                    processes[pid] = psutil.Process(pid)
                except psutil.NoSuchProcess:
                    self.worker_pop(pid)

        if self.servers_gevent:
            if respawn_time:
                # gevent servers take a bit longer to start so sleep a bit as a best effort to avoid downtime
                time.sleep(respawn_time + 1)
                for pid in self.servers_gevent:
                    self.worker_kill(pid, signal.SIGINT)

        timeout_gevent = time.monotonic()
        if respawn_time:
            timeout_gevent += config['limit_time_real']

        self.beat = 0.1
        while self.workers or self.servers_gevent:
            try:
                self.process_signals()
            except KeyboardInterrupt:
                self.logger.info("Forced shutdown.")
                break

            if is_main_server:
                self.process_zombie()
            else:
                for pid, proc in list(processes.items()):
                    if not proc.is_running():
                        self.worker_pop(pid)
                        processes.pop(pid)

            self.sleep()
            self.process_timeout()
            if self.servers_gevent and time.monotonic() > timeout_gevent:
                for pid in list(self.servers_gevent):
                    self.worker_kill(pid, signal.SIGKILL)

    def stop(self, graceful=True):
        if common.server_phoenix:
            # PreforkServer reloads gracefully, disable outdated mechanism
            common.server_phoenix = False

            respawn_time = self.fork_and_reload()
            self.stop_workers_gracefully(respawn_time=respawn_time)

            self.logger.info("Old server stopped")
            return

        if self.socket:
            self.socket.close()
        if graceful:
            super().stop()
            self.stop_workers_gracefully()
        else:
            self.logger.info("Stopping forcefully")

        for pid in list(self.servers_gevent):
            self.worker_kill(pid, signal.SIGKILL)
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGTERM)

    def run(self, preload, stop):
        self.start()

        rc = preload_registries(preload)

        if stop:
            self.stop()
            return rc

        # Empty the cursor pool, we dont want them to be shared among forked workers.
        sql_db.close_all()

        if os.environ.get('ODOO_READY_SIGHUP_PID'):
            os.kill(int(os.environ.pop('ODOO_READY_SIGHUP_PID')), signal.SIGHUP)

        self.logger.debug("starting")
        while True:
            try:
                # self.logger.debug("Multiprocess beat (%s)",time.time())
                self.process_signals()
                self.process_zombie()
                self.process_timeout()
                self.process_spawn()
                self.sleep()
            except KeyboardInterrupt:
                self.logger.debug("Multiprocess clean stop")
                self.stop()
                break
            except SystemExit:
                raise
            except BaseException as exc:
                self.logger.critical("Uncaught error in main loop, exiting...", exc_info=exc)
                self.stop(False)
                return -1

        return rc

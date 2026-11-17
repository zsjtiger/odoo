# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Threaded server: the HTTP and cron threads of a single process."""

import contextlib
import logging
import os
import select
import signal
import socket
import sys
import textwrap
import threading
import time
import contextvars
from concurrent.futures import ThreadPoolExecutor

import psutil

from odoo.http.server import HTTPSocket
from odoo.modules.registry import Registry
from odoo.orm.database import sql_db
from odoo.orm.models.cache import log_ormcache_stats
from odoo.tools import OrderedSet, config
from odoo.tools.misc import dumpstacks, mute_logger
from odoo.tools.system.osutil import memory_info

from . import common
from .common import CommonServer, SLEEP_INTERVAL, cron_database_list, set_limit_memory_hard
from .startup import preload_registries


_logger = logging.getLogger('odoo.service.server')


class ThreadedServer(CommonServer):
    def __init__(self, app):
        super().__init__(app)
        self.main_thread_id = threading.current_thread().ident
        # Variable keeping track of the number of calls to the signal handler defined
        # below. This variable is monitored by ``quit_on_signals()``.
        self.quit_signals_received = 0
        # True only while run()'s signal wait-loop is active. A SIGHUP that
        # arrives before the loop (start/preload/cron_spawn) or during teardown
        # must not raise KeyboardInterrupt: that would escape run() and kill the
        # process (130/129) instead of restarting cleanly.
        self.running = False

        self.stop_event = threading.Event()
        self.limits_reached_threads = set()
        self.limit_reached_time = None

    def signal_handler(self, sig, frame):
        if sig in [signal.SIGINT, signal.SIGTERM]:
            # shutdown on kill -INT or -TERM
            self.quit_signals_received += 1
            if self.quit_signals_received > 1:
                # logging.shutdown was already called at this point.
                sys.stderr.write("Forced shutdown.\n")
                os._exit(0)
            # interrupt run() to start shutdown
            raise KeyboardInterrupt()
        if hasattr(signal, 'SIGXCPU') and sig == signal.SIGXCPU:
            sys.stderr.write("CPU time limit exceeded! Shutting down immediately\n")
            sys.stderr.flush()
            os._exit(0)
        elif sig == signal.SIGHUP:
            if self.quit_signals_received:
                # A shutdown or phoenix restart is already pending. One file
                # change can emit several FS events, so a duplicate SIGHUP may
                # land during the teardown/_reexec path, which runs outside the
                # wait-loop's try/except; raising there would escape run(). The
                # pending restart reloads fresh code anyway.
                return
            # restart on kill -HUP
            common.server_phoenix = True
            self.quit_signals_received += 1
            if not self.running:
                # SIGHUP during the startup section, before the wait-loop: don't
                # raise (it would escape run()). quit_signals_received is now set,
                # so the loop exits at once when reached and the restart proceeds.
                return
            # interrupt run() to start shutdown
            raise KeyboardInterrupt()

    def process_limit(self):
        memory = memory_info(psutil.Process(os.getpid()))
        if config['limit_memory_soft'] and memory > config['limit_memory_soft']:
            self.logger.warning("Server memory limit (%s) reached.", memory)
            self.limits_reached_threads.add(threading.current_thread())

        for thread in threading.enumerate():
            thread_type = getattr(thread, 'type', None)
            if (not thread.daemon and thread_type != 'websocket') or thread_type == 'cron':
                # We apply the limits on cron threads and HTTP requests,
                # websocket requests excluded.
                if getattr(thread, 'start_time', None):
                    thread_execution_time = time.time() - thread.start_time
                    thread_limit_time_real = config['limit_time_real']
                    if (getattr(thread, 'type', None) == 'cron' and config['limit_time_real_cron'] >= 0):
                        thread_limit_time_real = config['limit_time_real_cron']
                    if thread_limit_time_real and thread_execution_time > thread_limit_time_real:
                        self.logger.warning(
                            "Thread %s virtual real time limit (%d/%ds) reached.",
                            thread, thread_execution_time, thread_limit_time_real)
                        self.limits_reached_threads.add(thread)
        # Clean-up threads that are no longer alive
        # e.g. threads that exceeded their real time,
        # but which finished before the server could restart.
        for thread in list(self.limits_reached_threads):
            if not thread.is_alive():
                self.limits_reached_threads.remove(thread)
        if self.limits_reached_threads:
            self.limit_reached_time = self.limit_reached_time or time.time()
        else:
            self.limit_reached_time = None

    def cron_thread(self, number):
        # Steve Reich timing style with thundering herd mitigation.
        #
        # On startup, all workers bind on a notification channel in
        # postgres so they can be woken up at will. At worst they wake
        # up every SLEEP_INTERVAL with a jitter. The jitter creates a
        # chorus effect that helps distribute on the timeline the moment
        # when individual worker wake up.
        #
        # On NOTIFY, all workers are awaken at the same time, sleeping
        # just a bit prevents they all poll the database at the exact
        # same time. This is known as the thundering herd effect.

        from odoo.addons.base.models.ir_cron import IrCron  # noqa: PLC0415

        cron_logger = self.logger.getChild(f'cron{number}')
        cron_logger.info("Alive")

        def _run_cron(cr):
            pg_conn = cr._cnx
            # LISTEN / NOTIFY doesn't work in recovery mode
            cr.execute("SELECT pg_is_in_recovery()")
            in_recovery = cr.fetchone()[0]
            if not in_recovery:
                cr.execute("LISTEN cron_trigger")
            else:
                cron_logger.warning("PG cluster in recovery mode, cron trigger not activated")
            cr.commit()
            check_all_time = 0.0  # last time that we listed databases, initialized far in the past
            all_db_names = []
            alive_time = time.monotonic()
            while config['limit_time_worker_cron'] <= 0 or (time.monotonic() - alive_time) <= config['limit_time_worker_cron']:
                select.select([pg_conn], [], [], SLEEP_INTERVAL + number)
                time.sleep(number / 100)
                try:
                    pg_conn.poll()
                except Exception:
                    if pg_conn.closed:
                        # connection closed, just exit the loop
                        return
                    raise
                notified = OrderedSet(
                    notif.payload
                    for notif in pg_conn.notifies
                    if notif.channel == 'cron_trigger'
                )
                pg_conn.notifies.clear()  # free resources

                if time.time() - SLEEP_INTERVAL > check_all_time:
                    # check all databases
                    # last time we checked them was `now - SLEEP_INTERVAL`
                    check_all_time = time.time()
                    # process notified databases first, then the other ones
                    all_db_names = OrderedSet(cron_database_list())
                    db_names = [
                        *(db for db in notified if db in all_db_names),
                        *(db for db in all_db_names if db not in notified),
                    ]
                else:
                    # restrict to notified databases only
                    db_names = notified.intersection(all_db_names)
                    if not db_names:
                        continue

                cron_logger.debug("polling for jobs (notified: %s)", notified)
                for db_name in db_names:
                    thread = threading.current_thread()
                    thread.start_time = time.time()
                    IrCron._process_jobs(db_name)
                    thread.start_time = None

        while True:
            try:
                conn = sql_db.db_connect(config['db_system'])
                with contextlib.closing(conn.cursor()) as cr:
                    _run_cron(cr)
                    cr._cnx.close()
                cron_logger.info("Max age (%ss) reached, recycling pg connection", config['limit_time_worker_cron'])
            except SystemExit:
                raise
            except BaseException:  # noqa: BLE001
                cron_logger.critical("Uncaught error in main loop. Retrying in 5 seconds...", exc_info=True)
                time.sleep(5)

    def cron_spawn(self):
        """ Start the above runner function in a daemon thread.

        The thread is a typical daemon thread: it will never quit and must be
        terminated when the main process exits - with no consequence (the processing
        threads it spawns are not marked daemon).

        """
        for i in range(config['max_cron_threads']):
            t = threading.Thread(target=self.cron_thread, args=(i,), name=f"odoo.service.cron.cron{i}", daemon=True)
            t.type = 'cron'
            t.start()

    def http_client_thread(self, client, address, prelude=b''):
        current_thread = threading.current_thread()
        try:
            current_thread.processing_http = True
            # timeout to avoid chrome headless preconnect during tests
            if config['test_enable']:
                client.settimeout(5)

            http_socket = HTTPSocket(client, address, prelude=prelude)
            http_socket.process_request()
        except BaseException:  # noqa: BLE001
            _logger.critical("Thread %s (%s) Exception occurred, quitting...",
                current_thread.name, current_thread.ident, exc_info=True)
        finally:
            client.close()
            current_thread.processing_http = False

    def http_server_thread(self, stop_event):
        try:
            thread_pool = ThreadPoolExecutor(
                max_workers=config.max_http_threads,
                thread_name_prefix='odoo.service.http.request',
            )

            if config.http_socket_activation:
                SD_LISTEN_FDS_START = 3
                server = socket.fromfd(
                    SD_LISTEN_FDS_START,
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                )
                _logger.info("HTTP service running through socket activation")
            else:
                server = socket.create_server(
                    (self.interface, self.port),
                    family=socket.AF_INET6 if ':' in config['http_interface'] else socket.AF_INET,
                    backlog=max(128, config.max_http_threads),
                    dualstack_ipv6=self.interface == '::',
                )
                host, port, *_ = server.getsockname()
                if host == '::':
                    host = '*'  # dual stack
                elif ':' in host:
                    host = f'[{host}]'
                if self.port == 0:
                    self.port = config['http_port'] = port
                _logger.info("HTTP service running on %s:%s", host, port)

            server.settimeout(1)  # it uses poll(2) under the hood
            with thread_pool, server:
                while not stop_event.is_set():
                    try:
                        client, address = server.accept()
                    except TimeoutError:
                        continue
                    else:
                        thread_pool.submit(contextvars.Context().run,
                            self.http_client_thread, client, address)

        except SystemExit:
            raise
        except BaseException:
            current_thread = threading.current_thread()
            _logger.critical("Thread %s (%s) Exception occurred, quitting...",
                current_thread.name, current_thread.ident, exc_info=True)

    def http_spawn(self):
        threading.Thread(
            target=self.http_server_thread,
            args=(self.stop_event,),
            name="odoo.service.httpd",
            daemon=True,
        ).start()

    def start(self, stop=False):
        self.logger.debug("setting signal handlers")
        set_limit_memory_hard()
        if os.name == 'posix':
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
            signal.signal(signal.SIGCHLD, self.signal_handler)
            signal.signal(signal.SIGHUP, self.signal_handler)
            signal.signal(signal.SIGXCPU, self.signal_handler)
            signal.signal(signal.SIGQUIT, dumpstacks)
            signal.signal(signal.SIGUSR1, log_ormcache_stats)
            signal.signal(signal.SIGUSR2, log_ormcache_stats)

        if config['test_enable'] or (config['http_enable'] and not stop):
            # some tests need the http daemon to be available...
            self.http_spawn()

    def stop(self):
        """ Shutdown the WSGI server. Wait for non daemon threads.
        """
        if common.server_phoenix:
            self.logger.info("Initiating server reload")
        else:
            self.logger.info("Initiating shutdown")
            self.logger.info("Hit CTRL-C again or send a second signal to force the shutdown.")

        stop_time = time.time()
        self.stop_event.set()

        super().stop()

        # Manually join() all threads before calling sys.exit() to allow a second signal
        # to trigger _force_quit() in case some non-daemon threads won't exit cleanly.
        # threading.Thread.join() should not mask signals (at least in python 2.5).
        me = threading.current_thread()
        self.logger.debug('current thread: %r', me)
        for thread in threading.enumerate():
            self.logger.debug('process %r (%r)', thread, thread.daemon)
            if (thread != me and not thread.daemon and thread.ident != self.main_thread_id and
                    thread not in self.limits_reached_threads):
                while thread.is_alive() and (time.time() - stop_time) < 1:
                    # We wait for requests to finish, up to 1 second.
                    self.logger.debug('join and sleep')
                    # Need a busyloop here as thread.join() masks signals
                    # and would prevent the forced shutdown.
                    thread.join(0.05)
                    time.sleep(0.05)

        log_ctx = contextlib.nullcontext()
        if config['log_db']:
            self.logger.info("Logging uses the database, stop logging then close DB connections")
            log_ctx = mute_logger('')

        current_process = psutil.Process()
        children = current_process.children(recursive=False)
        for child in children:
            self.logger.info("A child process was found, pid is %s, process may hang", child)

        with log_ctx:
            sql_db.close_all()
            self.logger.debug('--')
            logging.shutdown()

    def run(self, preload=None, stop=False):
        """ Start the http server and the cron thread then wait for a signal.

        The first SIGINT or SIGTERM signal will initiate a graceful shutdown while
        a second one if any will force an immediate exit.
        """
        with Registry._lock:
            self.start(stop=stop)
            rc = preload_registries(preload)

        if stop:
            if config['test_enable']:
                from odoo.tests.result import _logger as logger  # noqa: PLC0415
                with Registry.registries._lock:
                    for db, registry in Registry.registries.items():
                        report = registry._assertion_report
                        log = logger.error if not report.wasSuccessful() \
                         else logger.warning if not report.testsRun \
                         else logger.info
                        log("%s when loading database %r", report, db)
                        for test, errmsg in report.errors:
                            self.logger.info("Error: %s - %s", test, textwrap.shorten(errmsg, width=50))
                        for test, errmsg in report.failures:
                            self.logger.info("Failed: %s - %s", test, textwrap.shorten(errmsg, width=50))
            self.stop()
            return rc

        self.cron_spawn()

        # Wait for a first signal to be handled. (time.sleep will be interrupted
        # by the signal handler)
        try:
            # Arm the SIGHUP-raises-KeyboardInterrupt path only now, from inside
            # the try that catches it; setting it before the try would leave a
            # one-statement window where the raise escapes run().
            self.running = True
            while self.quit_signals_received == 0:
                self.process_limit()
                if self.limit_reached_time:
                    has_other_valid_requests = any(
                        not t.daemon and
                        t not in self.limits_reached_threads
                        for t in threading.enumerate()
                        if getattr(t, 'type', None) == 'http')
                    if (not has_other_valid_requests or
                            (time.time() - self.limit_reached_time) > SLEEP_INTERVAL):
                        # We wait there is no processing requests
                        # other than the ones exceeding the limits, up to 1 min,
                        # before asking for a reload.
                        self.logger.info("Dumping stacktrace of limit exceeding threads before reloading")
                        dumpstacks(thread_idents=[thread.ident for thread in self.limits_reached_threads])
                        self.reload()
                        # `reload` increments `self.quit_signals_received`
                        # and the loop will end after this iteration,
                        # therefore leading to the server stop.
                        # `reload` also sets the `common.server_phoenix` flag
                        # to tell the server to restart the server after shutting down.
                    else:
                        time.sleep(1)
                else:
                    time.sleep(SLEEP_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False

        self.stop()
        return rc

    def reload(self):
        os.kill(self.pid, signal.SIGHUP)

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Gevent server: the greenlet based HTTP server of the evented mode."""

import logging
import os
import signal
import socket

import psutil

from odoo.http.server import HTTPSocket
from odoo.orm.models.cache import log_ormcache_stats
from odoo.tools import config
from odoo.tools.misc import dumpstacks
from odoo.tools.system.osutil import memory_info

from .common import CommonServer, set_limit_memory_hard
from .startup import preload_registries


_logger = logging.getLogger('odoo.service.server')

GEVENT_STOP_TIMEOUT = 60


class GeventServer(CommonServer):
    def __init__(self, app):
        super().__init__(app)
        self.port = config['gevent_port']
        self.httpd = None

    def sigint_handler(self, sig, frame):
        if self.httpd:
            self.httpd._stop_event.set()

    def process_limits(self):
        restart = False
        if self.ppid != os.getppid():
            self.logger.warning("Parent changed: %s", self.pid)
            restart = True
        memory = memory_info(psutil.Process(self.pid))
        limit_memory_soft = config['limit_memory_soft_gevent'] or config['limit_memory_soft']
        if limit_memory_soft and memory > limit_memory_soft:
            self.logger.warning("Virtual memory limit reached: %s", memory)
            restart = True
        if restart:
            # suicide !!
            os.kill(self.pid, signal.SIGTERM)

    def watchdog(self, beat=4):
        import gevent  # noqa: PLC0415
        self.ppid = os.getppid()
        while True:
            self.process_limits()
            gevent.sleep(beat)

    def http_client_greenlet(self, client, address, prelude=b''):
        try:
            http_socket = HTTPSocket(client, address, prelude=prelude)
            http_socket.process_request()
        except BaseException:  # noqa: BLE001
            _logger.critical(
                "Uncaught error in longpolling greenlet, processing request from %s:%s",
                address[0], address[1], exc_info=True,
            )
        finally:
            client.close()

    def start(self):
        import gevent  # noqa: PLC0415
        import gevent.pool  # noqa: PLC0415
        import gevent.server  # noqa: PLC0415

        # Set process memory limit as an extra safeguard
        set_limit_memory_hard()
        if os.name == 'posix':
            signal.signal(signal.SIGINT, self.sigint_handler)
            signal.signal(signal.SIGQUIT, dumpstacks)
            signal.signal(signal.SIGUSR1, log_ormcache_stats)
            signal.signal(signal.SIGUSR2, log_ormcache_stats)
            gevent.spawn(self.watchdog)

        sock = socket.create_server(
            (self.interface, self.port),
            family=socket.AF_INET6 if ':' in self.interface else socket.AF_INET,
            backlog=128,
            reuse_port=hasattr(socket, 'SO_REUSEPORT'),
            dualstack_ipv6=self.interface == '::',
        )
        sock.setblocking(0)

        host, port, *_ = sock.getsockname()
        if host == '::':
            host = '*'  # dual stack
        elif ':' in host:
            host = f'[{host}]'
        if self.port == 0:
            self.port = config['gevent_port'] = port

        self.httpd = gevent.server.StreamServer(
            sock,
            self.http_client_greenlet,
            spawn=gevent.pool.Pool(),
        )

        # override StreamServer's `close` to end websocket connections
        # before we wait for all greenlets to finish & kill remaining.
        original_httpd_close = self.httpd.close
        super_stop = super().stop

        def httpd_close_override():
            original_httpd_close()
            super_stop()

        self.httpd.close = httpd_close_override

        self.logger.info("Evented/WebSocket service running on %s:%s", host, port)
        try:
            self.httpd.serve_forever(stop_timeout=GEVENT_STOP_TIMEOUT)
        except SystemExit:
            raise
        except BaseException as exc:
            self.logger.critical("Evented/WebSocket exception occurred, exitting...", exc_info=True)
            raise SystemExit(1) from exc

    def stop(self):
        if self.httpd:
            self.httpd._stop_event.set()
            # will call super().stop() in StreamServer.close
        else:
            super().stop()

    def run(self, preload, stop):
        if rc := preload_registries(preload):
            return rc
        self.start()
        self.stop()
        self.logger.info("Stopped")
        return 0

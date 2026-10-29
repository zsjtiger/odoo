# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Common infrastructure of the servers: the memory limits, the pipes, the database list and the base server."""

import errno
import logging
import os
import platform
import socket


from odoo.tools import config

if os.name == 'posix':
    # Unix only for workers
    import fcntl
    import resource


_logger = logging.getLogger('odoo.service.server')

server_phoenix = False

SLEEP_INTERVAL = 60     # 1 min


def set_limit_memory_hard():
    if platform.system() != 'Linux':
        return
    limit_memory_hard = config['limit_memory_hard']
    import odoo  # for eventd  # noqa: PLC0415
    if odoo.evented and config['limit_memory_hard_gevent']:
        limit_memory_hard = config['limit_memory_hard_gevent']
    if limit_memory_hard:
        rlimit = resource.RLIMIT_AS
        _soft, hard = resource.getrlimit(rlimit)
        resource.setrlimit(rlimit, (limit_memory_hard, hard))


def pipe_new():
    pipe = os.pipe()
    for fd in pipe:
        # non_blocking
        flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        # close_on_exec
        flags = fcntl.fcntl(fd, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFD, flags)
    return pipe


def pipe_ping(pipe):
    try:
        os.write(pipe[1], b'.')
    except BlockingIOError:
        pass


def empty_pipe(fd):
    try:
        while os.read(fd, 1):
            pass
    except BlockingIOError:
        pass


def cron_database_list():
    from odoo.modules.db import list_dbs  # noqa: PLC0415
    return config['db_name'] or list_dbs(force=True)


# ----------------------------------------------------------
# Servers: Threaded, Gevented and Prefork
# ----------------------------------------------------------

class CommonServer:
    _on_stop_funcs = []

    def __init__(self, app):
        self.app = app
        # config
        self.interface = config['http_interface'] or '0.0.0.0'
        self.port = config['http_port']
        # runtime
        self.pid = os.getpid()
        self.logger = _logger.getChild(self.__class__.__name__)

    def close_socket(self, sock):
        """ Closes a socket instance cleanly
        :param sock: the network socket to close
        :type sock: socket.socket
        """
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError as e:
            if e.errno == errno.EBADF:
                # Werkzeug > 0.9.6 closes the socket itself (see commit
                # https://github.com/mitsuhiko/werkzeug/commit/4d8ca089)
                return
            # On OSX, socket shutdowns both sides if any side closes it
            # causing an error 57 'Socket is not connected' on shutdown
            # of the other side (or something), see
            # http://bugs.python.org/issue4397
            # note: stdlib fixed test, not behavior
            if e.errno != errno.ENOTCONN or platform.system() not in ['Darwin', 'Windows']:
                raise
        sock.close()

    @classmethod
    def on_stop(cls, func):
        """ Register a cleanup function to be executed when the server stops """
        cls._on_stop_funcs.append(func)

    def stop(self):
        for func in self._on_stop_funcs:
            try:
                self.logger.debug("on_close call %s", func)
                func()
            except Exception:  # noqa: BLE001
                self.logger.warning("Exception in %s", func.__name__, exc_info=True)

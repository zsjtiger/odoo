# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The servers of Odoo, and the entry points that start them.

- ``threaded``: one process, threads for the HTTP requests and the crons;
- ``gevent_server``: one process, greenlets, in the evented mode;
- ``prefork``: a supervisor forking the HTTP and cron workers of ``worker``.

``start`` picks the server from the configuration and runs it. ``reloader``
restarts the server when the source files change, ``startup`` loads the
server-wide modules and preloads the registries.
"""
import logging
import os
import platform
import signal
import sys
import threading

from odoo.tools import config

from . import common, reloader
from .gevent_server import GeventServer
from .prefork import PreforkServer
from .startup import _reexec, load_server_wide_modules, preload_registries  # noqa: F401
from .threaded import ThreadedServer

# Windows shim: the reload handler of the posix servers uses SIGHUP
if os.name != 'posix':
    signal.SIGHUP = -1

_logger = logging.getLogger('odoo.service.server')

server = None


def start(preload=None, stop=False):
    """ Start the odoo http server and cron processor.
    """
    global server  # noqa: PLW0603

    load_server_wide_modules()
    import odoo  # noqa: PLC0415
    from odoo.http.router import root  # noqa: PLC0415

    if odoo.evented:
        server = GeventServer(root)
    elif config['workers']:
        if config['test_enable']:
            _logger.warning("Unit testing in workers mode could fail; use --workers 0.")

        server = PreforkServer(root)
    else:
        if platform.system() == "Linux" and sys.maxsize > 2**32 and "MALLOC_ARENA_MAX" not in os.environ:
            # glibc's malloc() uses arenas [1] in order to efficiently handle memory allocation of multi-threaded
            # applications. This allows better memory allocation handling in case of multiple threads that
            # would be using malloc() concurrently [2].
            # Due to the python's GIL, this optimization have no effect on multithreaded python programs.
            # Unfortunately, a downside of creating one arena per cpu core is the increase of virtual memory
            # which Odoo is based upon in order to limit the memory usage for threaded workers.
            # On 32bit systems the default size of an arena is 512K while on 64bit systems it's 64M [3],
            # hence a threaded worker will quickly reach it's default memory soft limit upon concurrent requests.
            # We therefore set the maximum arenas allowed to 2 unless the MALLOC_ARENA_MAX env variable is set.
            # Note: Setting MALLOC_ARENA_MAX=0 allow to explicitly set the default glibs's malloc() behaviour.
            #
            # [1] https://sourceware.org/glibc/wiki/MallocInternals#Arenas_and_Heaps
            # [2] https://www.gnu.org/software/libc/manual/html_node/The-GNU-Allocator.html
            # [3] https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c;h=00ce48c;hb=0a8262a#l862
            try:
                import ctypes  # noqa: PLC0415
                libc = ctypes.CDLL("libc.so.6")
                M_ARENA_MAX = -8
                assert libc.mallopt(ctypes.c_int(M_ARENA_MAX), ctypes.c_int(2))
            except Exception:  # noqa: BLE001
                _logger.warning("Could not set ARENA_MAX through mallopt()", exc_info=True)
        server = ThreadedServer(root)

    watcher = None
    if 'reload' in config['dev_mode'] and not odoo.evented:
        watcher = reloader.start_watcher()

    rc = server.run(preload, stop)

    if watcher:
        watcher.stop()
    # like the legend of the phoenix, all ends with beginnings
    if common.server_phoenix:
        _reexec()

    return rc if rc else 0


def restart():
    """ Restart the server
    """
    if os.name == 'nt':
        # run in a thread to let the current thread return response to the caller.
        threading.Thread(target=_reexec).start()
    else:
        os.kill(server.pid, signal.SIGHUP)

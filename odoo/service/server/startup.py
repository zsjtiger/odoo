# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Startup of the server: the server-wide modules, the preloading of the registries and the re-execution."""

import contextlib
import logging
import os
import signal
import subprocess
import sys
import threading
import time


from odoo import api
from odoo.modules.registry import Registry
from odoo.orm.database import sql_db
from odoo.tools import config
from odoo.tools.misc import stripped_sys_argv
from odoo.tools.profiling import gc, profiler


_logger = logging.getLogger('odoo.service.server')


def load_server_wide_modules():
    from odoo.modules.module import load_openerp_module  # noqa: PLC0415
    with gc.disabling_gc():
        for m in config['server_wide_modules']:
            try:
                load_openerp_module(m)
            except Exception:
                msg = ''
                if m == 'web':
                    msg = """
    The `web` module is provided by the addons found in the `openerp-web` project.
    Maybe you forgot to add those addons in your addons_path configuration."""
                _logger.exception('Failed to load server-wide module `%s`.%s', m, msg)


_RELOAD_EXIT_CODE = 75  # EX_TEMPFAIL from sysexits.h: child asks supervisor to respawn


def _reexec(updated_modules=None):
    """reexecute openerp-server process with (nearly) the same arguments.

    Uses `os.execve` by default for pycharm environments. For debugpy
    environments, use a supervisor/subprocess design to respawn the server
    as a subprocess on each reload which matches debugpy's requirements.
    """
    exe = os.path.basename(sys.executable)
    args = stripped_sys_argv()
    if updated_modules:
        args += ["-u", ','.join(updated_modules)]
    if not args or args[0] not in (sys.executable, exe):
        args.insert(0, sys.executable)

    # debugpy sets this environment variable at the start of debug sessions.
    # We can use that to make sure we are in that environment
    if os.environ.get('DEBUGPY_RUNNING') == 'true':
        import odoo  # noqa: PLC0415
        if not odoo.evented:
            # Subprocess: kill on reload to trigger a respawn by the supervisor.
            if os.environ.get('ODOO_RELOAD_CHILD'):
                os._exit(_RELOAD_EXIT_CODE)
            # First generation: become a supervisor that respawns the actual
            # server on each reload. Each supervised child runs as a debugger
            # sub-session via debugpy's subProcess hook.
            sock_fd = os.environ.get('ODOO_HTTP_SOCKET_FD')
            pass_fds = (int(sock_fd),) if sock_fd else ()
            env = os.environ.copy()
            env['ODOO_RELOAD_CHILD'] = '1'
            rc = _RELOAD_EXIT_CODE
            while rc == _RELOAD_EXIT_CODE:
                rc = subprocess.Popen(args, env=env, pass_fds=pass_fds).wait()
            sys.exit(rc)

    if os.name == 'posix':
        # execve resets caught signal handlers to their default disposition
        # (SIGHUP terminates -> exit 129) but preserves SIG_IGN, so a SIGHUP that
        # lands before the re-exec'd process reinstalls its handler would kill it.
        # The reload loads fresh code, so dropping SIGHUPs across the gap is safe.
        # Guard on posix: signal.SIGHUP is a shim (-1) on nt and would raise here.
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    # We should keep the LISTEN_* environment variabled in order to support socket activation on reexec
    os.execve(sys.executable, args, os.environ)


def preload_registries(dbnames):
    """ Preload a registries, possibly run a test file."""
    # TODO: move all config checks to args dont check tools.config here
    dbnames = dbnames or []
    rc = 0

    preload_profiler = contextlib.nullcontext()

    registries_size = int(os.environ.get('ODOO_REGISTRY_LRU_SIZE') or 0)
    if not registries_size and os.name == 'posix':
        # Size the LRU depending of the memory limits
        # A registry takes 10MB of memory on average, so we reserve
        # 10Mb (registry) + 5Mb (working memory) per registry
        avgsz = 15 * 1024 * 1024
        limit_memory_soft = config['limit_memory_soft'] if config['limit_memory_soft'] > 0 else (2048 * 1024 * 1024)
        registries_size = (limit_memory_soft // avgsz) or 1
    elif not registries_size and len(dbnames) > Registry.registries.count:
        # If we give a list of databases higher and did not specify the size,
        # use the number of preloaded databases as the limit.
        registries_size = len(dbnames)
    if registries_size:
        Registry.registries.count = registries_size

    if registry_idle_timeout := os.environ.get("ODOO_REGISTRY_MAX_IDLE_TIMEOUT"):
        Registry.idle_timeout = int(registry_idle_timeout)

    for dbname in dbnames:
        if os.environ.get('ODOO_PROFILE_PRELOAD'):
            interval = float(os.environ.get('ODOO_PROFILE_PRELOAD_INTERVAL', '0.1'))
            collectors = [profiler.PeriodicCollector(interval=interval)]
            if os.environ.get('ODOO_PROFILE_PRELOAD_SQL'):
                collectors.append('sql')
            preload_profiler = profiler.Profiler(db=dbname, collectors=collectors)
        try:
            with preload_profiler:
                threading.current_thread().dbname = dbname
                update_module = config['init'] or config['update'] or config['reinit']

                registry = Registry.new(dbname, update_module=update_module, install_modules=config['init'], upgrade_modules=config['update'], reinit_modules=config['reinit'])

                # run post-install tests
                if config['test_enable']:
                    from odoo.tests import loader  # noqa: PLC0415
                    t0 = time.time()
                    t0_sql = sql_db.sql_counter
                    module_names = sorted(registry.updated_modules if update_module else
                                    registry._init_modules)
                    _logger.info("Starting post tests")
                    tests_before = registry._assertion_report.testsRun
                    post_install_suite = loader.make_suite(module_names, 'post_install')
                    if post_install_suite.has_http_case():
                        with registry.cursor() as cr:
                            env = api.Environment(cr, api.SUPERUSER_ID, {})
                            env.registry._assertion_report = registry._assertion_report
                            env['ir.qweb']._pregenerate_assets_bundles()
                    result = loader.run_suite(post_install_suite, global_report=registry._assertion_report)
                    registry._assertion_report.update(result)
                    _logger.info("%d post-tests in %.2fs, %s queries",
                                registry._assertion_report.testsRun - tests_before,
                                time.time() - t0,
                                sql_db.sql_counter - t0_sql)

                    registry._assertion_report.log_stats()
                if registry._assertion_report and not registry._assertion_report.wasSuccessful():
                    rc += 1
        except Exception:
            _logger.critical('Failed to initialize database `%s`.', dbname, exc_info=True)
            return -1
    return rc

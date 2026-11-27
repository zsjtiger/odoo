# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The system: the processes, the stacks, the environment and the exceptions."""

from __future__ import annotations
import logging
import os
import sys
import threading
import time
import traceback
import typing
from contextlib import ContextDecorator
from itertools import groupby as itergroupby
from odoo.tools.config import config
from odoo.tools.system.which import which

if typing.TYPE_CHECKING:
    pass


_logger = logging.getLogger('odoo.tools.misc')


real_time = time.time.__call__  # type: ignore


def exception_to_unicode(e):
    if getattr(e, 'args', ()):
        return "\n".join(map(str, e.args))
    try:
        return str(e)
    except Exception:
        return "Unknown message"


def find_pg_tool(name):
    path = None
    if config['pg_path'] and config['pg_path'] != 'None':
        path = config['pg_path']
    try:
        return which(name, path=path)
    except OSError:
        raise Exception('Command `%s` not found.' % name)


def exec_pg_environ():
    """
    Force the database PostgreSQL environment variables to the database
    configuration of Odoo.

    Note: When pg_restore/pg_dump require an explicit password, it is necessary
    to pass the postgres user password in the PGPASSWORD environment variable or
    in a special .pgpass file.

    See also https://www.postgresql.org/docs/current/libpq-envars.html
    """
    env = os.environ.copy()
    if config['db_host']:
        env['PGHOST'] = config['db_host']
    if config['db_port']:
        env['PGPORT'] = str(config['db_port'])
    if config['db_user']:
        env['PGUSER'] = config['db_user']
    if config['db_password']:
        env['PGPASSWORD'] = config['db_password']
    if config['db_app_name']:
        env['PGAPPNAME'] = config['db_app_name'].replace('{pid}', f'env{os.getpid()}')[:63]
    if config['db_sslmode']:
        env['PGSSLMODE'] = config['db_sslmode']
    return env


def stripped_sys_argv(*strip_args):
    """Return sys.argv with some arguments stripped, suitable for reexecution or subprocesses"""
    strip_args = sorted(set(strip_args) | {'--save', '-u', '--update', '-i', '--init', '--i18n-overwrite'})
    assert all(config.parser.has_option(s) for s in strip_args)
    takes_value = dict((s, config.parser.get_option(s).takes_value()) for s in strip_args)

    longs, shorts = list(tuple(y) for _, y in itergroupby(strip_args, lambda x: x.startswith('--')))
    longs_eq = tuple(l + '=' for l in longs if takes_value[l])

    args = sys.argv[:]

    def strip(args, i):
        return args[i].startswith(shorts) \
            or args[i].startswith(longs_eq) or (args[i] in longs) \
            or (i >= 1 and (args[i - 1] in strip_args) and takes_value[args[i - 1]])

    return [x for i, x in enumerate(args) if not strip(args, i)]


def dumpstacks(sig=None, frame=None, thread_idents=None, log_level=logging.INFO):
    """ Signal handler: dump a stack trace for each existing thread or given
    thread(s) specified through the ``thread_idents`` sequence.
    """
    code = []

    def extract_stack(stack):
        for filename, lineno, name, line in traceback.extract_stack(stack):
            yield 'File: "%s", line %d, in %s' % (filename, lineno, name)
            if line:
                yield "  %s" % (line.strip(),)

    def find_env(stack):
        from odoo.api import Environment  # noqa: PLC0415

        for frame, _ in traceback.walk_stack(stack):
            self = frame.f_locals.get('self')
            if not self:
                continue
            if not hasattr(self, 'env'):
                continue
            if not isinstance(self.env, Environment):
                continue
            return self.env
        return None

    # code from http://stackoverflow.com/questions/132058/getting-stack-trace-from-a-running-python-application#answer-2569696
    # modified for python 2.5 compatibility
    threads_info = {th.ident: {'repr': repr(th),
                               'uid': getattr(th, 'uid', 'n/a'),
                               'dbname': getattr(th, 'dbname', 'n/a'),
                               'url': getattr(th, 'url', 'n/a'),
                               'query_count': getattr(th, 'query_count', 'n/a'),
                               'query_time': getattr(th, 'query_time', None),
                               'perf_t0': getattr(th, 'perf_t0', None)}
                    for th in threading.enumerate()}
    for threadId, stack in sys._current_frames().items():
        if not thread_idents or threadId in thread_idents:
            thread_info = threads_info.get(threadId, {})
            query_time = thread_info.get('query_time')
            perf_t0 = thread_info.get('perf_t0')
            remaining_time = None
            if query_time is not None and perf_t0:
                remaining_time = '%.3f' % (real_time() - perf_t0 - query_time)
                query_time = '%.3f' % query_time
            # qc:query_count qt:query_time pt:python_time (aka remaining time)
            code.append("\n# Thread: %s (db:%s) (uid:%s) (url:%s) (qc:%s qt:%s pt:%s)" %
                        (thread_info.get('repr', threadId),
                         thread_info.get('dbname', 'n/a'),
                         thread_info.get('uid', 'n/a'),
                         thread_info.get('url', 'n/a'),
                         thread_info.get('query_count', 'n/a'),
                         query_time or 'n/a',
                         remaining_time or 'n/a'))

            env = find_env(stack)
            if env:
                stopwatches = env.cr.cache.get('base_automation_stopwatches')
                last_stopwatches = list(env.cr.cache.get('base_automation_last_stopwatches', []))
                now = time.monotonic()
                if stopwatches is not None:
                    for automation_id, start_time in last_stopwatches:
                        # this automated action is currently running
                        duration = now - start_time
                        stopwatches[automation_id] = stopwatches.get(automation_id, 0) + duration
                    code.append(f"# Base Automations dict[id, duration]: {stopwatches}")
                    for automation_id, start_time in last_stopwatches:
                        # this automated action is currently running
                        duration = now - start_time
                        stopwatches[automation_id] -= duration

            for line in extract_stack(stack):
                code.append(line)

    import odoo  # eventd
    if odoo.evented:
        # code from http://stackoverflow.com/questions/12510648/in-gevent-how-can-i-dump-stack-traces-of-all-running-greenlets
        import gc
        from greenlet import greenlet
        for ob in gc.get_objects():
            if not isinstance(ob, greenlet) or not ob:
                continue
            code.append("\n# Greenlet: %r" % (ob,))
            for line in extract_stack(ob.gr_frame):
                code.append(line)

    _logger.log(log_level, "\n".join(code))


class replace_exceptions(ContextDecorator):
    """
    Hide some exceptions behind another error. Can be used as a function
    decorator or as a context manager.

    .. code-block:

        @route('/super/secret/route', auth='public')
        @replace_exceptions(AccessError, by=NotFound())
        def super_secret_route(self):
            if not request.session.uid:
                raise AccessError("Route hidden to non logged-in users")
            ...

        def some_util():
            ...
            with replace_exceptions(ValueError, by=UserError("Invalid argument")):
                ...
            ...

    :param exceptions: the exception classes to catch and replace.
    :param by: the exception to raise instead.
    """
    def __init__(self, *exceptions, by):
        if not exceptions:
            raise ValueError("Missing exceptions")

        wrong_exc = next((exc for exc in exceptions if not issubclass(exc, Exception)), None)
        if wrong_exc:
            raise TypeError(f"{wrong_exc} is not an exception class.")

        self.exceptions = exceptions
        self.by = by

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None and issubclass(exc_type, self.exceptions):
            if isinstance(self.by, type) and exc_value.args:
                # copy the message
                raise self.by(exc_value.args[0]) from exc_value
            else:
                raise self.by from exc_value

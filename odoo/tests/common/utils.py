# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Helpers of the test framework: the constants, the database name and the test logger."""

from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import typing
from concurrent.futures import Future
import freezegun
import odoo.cli
import odoo.models
import odoo.orm.models.registry
from odoo import api
from odoo.tools import config
from odoo.tools.misc import str2bool
from odoo.tools.safe_eval import safe_whitelist
from odoo.tools.xml.xml_utils import _validate_xml
import odoo.addons.base
from odoo.tests import case

if typing.TYPE_CHECKING:
    pass


_logger = logging.getLogger('odoo.tests.common')


if odoo.cli.COMMAND in ('server', 'start') and not config['test_enable']:
    _logger.error(
        "Importing test framework"
        ", avoid importing from business modules and when not running in test mode",
        stack_info=True,
    )
else:
    _logger.info("Importing test framework", stack_info=_logger.isEnabledFor(logging.DEBUG))


HOST = '127.0.0.1'


ADMIN_USER_ID = api.SUPERUSER_ID


CHECK_BROWSER_SLEEP = 0.1 # seconds


CHECK_BROWSER_ITERATIONS = 100


BROWSER_WAIT = CHECK_BROWSER_SLEEP * CHECK_BROWSER_ITERATIONS # seconds


DEFAULT_SUCCESS_SIGNAL = 'test successful'


TEST_CURSOR_COOKIE_NAME = 'test_request_key'


DISABLE_TIMEOUTS = str2bool(os.getenv('ODOO_TEST_DISABLE_TIMEOUT', '0'))


IGNORED_MSGS = re.compile(r"""
    failed\ to\ fetch  # base error
  | connectionlosterror:  # conversion by offlineFailToFetchErrorHandler
  | assetsloadingerror: # lazy loaded bundle
""", flags=re.VERBOSE | re.IGNORECASE).search


def get_db_name():
    dbnames = odoo.tools.config['db_name']
    # If the database name is not provided on the command-line,
    # use the one on the thread (which means if it is provided on
    # the command-line, this will break when installing another
    # database from XML-RPC).
    if not dbnames and hasattr(threading.current_thread(), 'dbname'):
        return threading.current_thread().dbname
    if len(dbnames) > 1:
        sys.exit("-d/--database/db_name has multiple database, please provide a single one")
    return dbnames[0]


def test_xsd(url=None, path=None, skip=False):
    def decorator(func):
        def wrapped_f(self, *args, **kwargs):
            if not skip:
                xmls = func(self, *args, **kwargs)
                _validate_xml(self.env, url, path, xmls)
        return wrapped_f
    return decorator


def run(gen_func):
    def done(f):
        try:
            try:
                r = f.result()
            except Exception as e:
                f = coro.throw(e)
            else:
                f = coro.send(r)
        except StopIteration:
            return

        assert isinstance(f, Future), f"coroutine must yield futures, got {f}"
        f.add_done_callback(done)

    coro = gen_func()
    try:
        next(coro).add_done_callback(done)
    except StopIteration:
        return


def can_import(module):
    """ Checks if <module> can be imported, returns ``True`` if it can be,
    ``False`` otherwise.

    To use with ``unittest.skipUnless`` for tests conditional on *optional*
    dependencies, which may or may be present but must still be tested if
    possible.
    """
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    else:
        return True


class freeze_time:
    """ Object to replace the freezegun in Odoo test suites
        It properly handles the test classes decoration
        Also, it can be used like the usual method decorator or context manager
    """
    _freeze_time = staticmethod(freezegun.freeze_time)

    def __init__(self, time_to_freeze=None, tz_offset=0, tick=False, as_kwarg='', auto_tick_seconds=0):
        self.freezer = self._freeze_time(
            time_to_freeze=time_to_freeze,
            tz_offset=tz_offset,
            tick=tick,
            as_kwarg=as_kwarg,
            auto_tick_seconds=auto_tick_seconds,
        )

    def __call__(self, arg):
        if isinstance(arg, type) and issubclass(arg, case.TestCase):
            arg.freeze_time = self
            return arg

        return self.freezer(arg)

    def __enter__(self):
        return self.freezer.start()

    def __exit__(self, *args):
        self.freezer.stop()

    start = __enter__
    stop = __exit__


freezegun.freeze_time = freeze_time


safe_whitelist.add_class('freezegun.api.FakeDate')


safe_whitelist.add_class('freezegun.api.FakeDatetime')


safe_whitelist.add_function('FakeDate.*')


safe_whitelist.add_function('FakeDatetime.*')


safe_whitelist.add_instance('odoo.orm.database.sql_db.TestCursor')


safe_whitelist.add_instance('odoo.tests.*')


safe_whitelist.add_instance('unittest.mock.MagicMock')


safe_whitelist.add_instance('unittest.mock.Mock')

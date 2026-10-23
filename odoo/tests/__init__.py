# ruff: noqa: F401
"""
Odoo unit testing framework, based on Python unittest.

Some files as case.py, resut.py, suite.py are higly modified versions of unitest
See https://github.com/python/cpython/tree/3.10/Lib/unittest for reference files.
"""

from . import common
from .common import ADMIN_USER_ID, Approx, BROWSER_WAIT, BaseCase, BlockedRequest, CHECK_BROWSER_ITERATIONS, CHECK_BROWSER_SLEEP, ChromeBrowser, ChromeBrowserException, Command, CrossModule, DEFAULT_SUCCESS_SIGNAL, DISABLE_TIMEOUTS, DummyRLock, HOST, HttpCase, IGNORED_MSGS, JsonRpcException, Like, MockHTTPClient, NoScreencast, Opener, QueryLike, RecordCapturer, RegistryRLock, Response, Screencaster, TEST_CURSOR_COOKIE_NAME, TransactionCase, Transport, WhitespaceInsensitive, can_import, flushing_cursor, freeze_time, get_db_name, loaded_demo_data, new_test_user, no_retry, patch, release_test_lock, run, save_test_file, standalone, standalone_tests, tagged, test_xsd, users, warmup
from .form import Form, O2MProxy, M2MProxy

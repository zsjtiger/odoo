# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The module :mod:`odoo.tests.common` provides unittest test cases and a few
helpers and classes to write tests.

The names are split by concern in the submodules: ``utils`` (constants and
helpers), ``decorators`` (tags and parametrization), ``locks`` (the locks of the
test registry), ``transaction`` (the transaction test case), ``base`` (the base
test case and the assertion helpers), ``mocks`` (the HTTP mocks), ``browser``
(the headless Chrome) and ``http_case`` (the HTTP test case). The package
re-exports them, so that ``odoo.tests.common`` keeps its names.
"""
from .utils import *  # noqa: F403
from .decorators import *  # noqa: F403
from .locks import *  # noqa: F403
from .mocks import *  # noqa: F403
from .base import *  # noqa: F403
from .transaction import *  # noqa: F403
from .browser import *  # noqa: F403
from .http_case import *  # noqa: F403


# the names of the former module that are used through odoo.tests, the submodules are not exported
__all__ = [
    'ADMIN_USER_ID',
    'Approx',
    'BROWSER_WAIT',
    'BaseCase',
    'BlockedRequest',
    'CHECK_BROWSER_ITERATIONS',
    'CHECK_BROWSER_SLEEP',
    'ChromeBrowser',
    'ChromeBrowserException',
    'Command',
    'CrossModule',
    'DEFAULT_SUCCESS_SIGNAL',
    'DISABLE_TIMEOUTS',
    'DummyRLock',
    'HOST',
    'HttpCase',
    'IGNORED_MSGS',
    'JsonRpcException',
    'Like',
    'MockHTTPClient',
    'NoScreencast',
    'Opener',
    'QueryLike',
    'RecordCapturer',
    'RegistryRLock',
    'Response',
    'Screencaster',
    'TEST_CURSOR_COOKIE_NAME',
    'TransactionCase',
    'Transport',
    'WhitespaceInsensitive',
    'can_import',
    'flushing_cursor',
    'freeze_time',
    'get_db_name',
    'loaded_demo_data',
    'new_test_user',
    'no_retry',
    'patch',
    'release_test_lock',
    'run',
    'save_test_file',
    'standalone',
    'standalone_tests',
    'tagged',
    'test_xsd',
    'users',
    'warmup',
]

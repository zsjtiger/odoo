"""The modes of the registry in the test cases: the test cursor, the read-only registry and the checks of the test cursor."""

from __future__ import annotations

import typing
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch
from werkzeug.exceptions import BadRequest
import odoo.cli
from odoo.http import request
from odoo.modules.registry import Registry
from odoo.orm.database.sql_db import Cursor
from odoo.tests import test_cursor
from ..utils import TEST_CURSOR_COOKIE_NAME, _logger
from ..locks import DummyRLock, _registry_test_lock

if typing.TYPE_CHECKING:
    pass


@contextmanager
def registry_test_mode(cls, *, cr: Cursor | None = None, registry: Registry | None = None):
    """ Entering registry test mode.

    New cursors returned by the registry will be instances of `TestCursor`
    which will wrap the current cursor.

    Defined in BaseCase because used by upgrade for IntegrityCase.
    This should be used on TransactionCase only.
    """
    assert not cls._registry_patched, 'Can only patch registry once'
    if cr is None:
        cr = cls.cr
    if registry is None:
        registry = cls.registry
    assert cr, 'No cursor'
    assert registry, 'No registry'

    def _patched_cursor(readonly: bool = False):
        return test_cursor.TestCursor(
            cr, _registry_test_lock, readonly and cls._registry_readonly_enabled
        )

    try:
        from odoo.addons.bus.tools import misc as bus_misc  # noqa: PLC0415
    except ImportError:
        additional_patches = ()
    else:
        og_db_connect = bus_misc.db_connect

        def _patched_ws_db_connect(to, allow_uri=False, readonly=False):
            # acquire_cursor() opens a cursor via db_connect(db_name) directly instead
            # of going through Registry(db_name).cursor(), bypassing the patch above.
            # Redirect it to the test's cursor too.
            if to == cr.dbname:

                class _TestConnection:
                    def cursor(self):
                        return _patched_cursor(readonly)

                return _TestConnection()
            return og_db_connect(to, allow_uri=allow_uri, readonly=readonly)

        additional_patches = (
            patch.object(bus_misc, 'db_connect', _patched_ws_db_connect),
        )

    def get_sequences(cr):
        return registry.registry_sequence, registry.cache_sequences.copy()

    with ExitStack() as stack:
        for additional_patch in additional_patches:
            stack.enter_context(additional_patch)
        stack.enter_context(patch.object(cls, '_registry_patched', True))
        # New cursor should point to the test's cursor
        stack.enter_context(patch.object(registry, 'cursor', _patched_cursor))
        # Disable locking and signaling
        stack.enter_context(patch.object(Registry, '_lock', DummyRLock()))
        stack.enter_context(patch.object(registry, 'setup_signaling', return_value=None))  # noop
        yield


def set_registry_readonly_mode(cls, enabled: bool):
    assert cls._registry_patched, 'Registry is not patched'

    cls._registry_readonly_enabled = enabled


def assertCanOpenTestCursor(self):
    """ Asserts that we can currently open a test cursor. """
    if odoo.modules.module.current_test is not self:
        message = f"Trying to open a test cursor for {self.canonical_tag} while already in a test {odoo.modules.module.current_test.canonical_tag}"
        _logger.runbot(message)
        raise BadRequest(message)
    if isinstance(request, Mock):
        return
    if not request or self.http_request_allow_all:
        return
    http_request_required_key = self.http_request_key
    # Read from the raw transmitted cookies rather than request.cookies.
    # The latter can be cleared by a handler (e.g. the force_guest auth
    # method in livechat CORS flows) before a new cursor is opened, which
    # would incorrectly fail this check even though the cookie was sent by
    # the test.
    http_request_key = request.httprequest.cookies.get(TEST_CURSOR_COOKIE_NAME)
    if http_request_key != http_request_required_key:
        expected = http_request_required_key
        if not expected:
            expected = 'None (request are not enabled)'
        _logger.runbot(
            'Request with path %s has been ignored during test as it '
            'it does not contain the test_cursor cookie or it is expired.'
            ' (required "%s", got "%s")',
            request.httprequest.path, expected, http_request_key
        )
        raise BadRequest(
            'Request ignored during test as it does not contain the required cookie.'
        )

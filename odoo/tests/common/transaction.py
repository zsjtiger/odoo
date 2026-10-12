# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Transaction test case, and the cursors of the transactions of the tests."""

from __future__ import annotations

import traceback
import typing
from collections import deque
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from unittest.mock import patch
from passlib.context import CryptContext
import odoo.cli
import odoo.models
import odoo.orm.models.registry
from odoo import api, fields
from odoo.orm.models.environments import CacheLayer
from odoo.modules.registry import Registry
from odoo.orm.database.sql_db import Cursor
from odoo.tools import mute_logger
from odoo.tools.lru import LRU
import odoo.addons.base
from odoo.tests import test_cursor

if typing.TYPE_CHECKING:
    pass

from .utils import TEST_CURSOR_COOKIE_NAME, _logger, freeze_time, get_db_name
from .base import BaseCase
from .locks import _disable_flushing_cursor, _registry_test_lock, release_test_lock

@contextmanager
def flushing_cursor(cr: Cursor):
    """ Simulate a commit on a cursor (without comitting) and reset on exit.

    Run this on the main cursor when creating test cursors so that they can see
    changes made on the main cursor. You can still continue using the main
    cursor inside the block, it will be flushed on exit and then reset.
    """
    assert isinstance(odoo.modules.module.current_test, TransactionCase), "only available for TransactionCase"

    if _disable_flushing_cursor:
        # execution of wkhtml happens in parallel, we don't want to flush the
        # cursor in that case
        yield
        return

    if cr.transaction is None:  # no environment to clear
        cr.flush()
        yield
        return

    # simluate cr.commit()
    state_stack = cr.transaction._state_stack__
    registry_invalidated = cr.transaction._registry_invalidated
    closing = cr._closing
    # preserve registry_invalidated flag which is reset when committing
    # sum them after yielding
    try:
        # Since we simulate an empty stack, make sure the parent layer is set as
        # the cache on the registry. This ensures that existing caches are not
        # affected by updating parent layers.
        registry_caches = cr.transaction.registry.registry_caches__
        for name in registry_caches:
            layer = cr.transaction.ormcaches__[name]
            parent = layer.parent
            if parent is None:
                # simulate signaling already here
                layer.parent = parent = LRU(999999)
                layer.update_parent()
            registry_caches[name] = (registry_caches[name][0], parent)

        cr._closing = True  # do a quick clean
        cr.transaction._state_stack__ = []  # replace the stack
        with cr.transaction.committing():
            pass  # no real commit
        # restore the stack
        cr.transaction._state_stack__ = state_stack
        cr._closing = closing

        try:
            yield
        finally:
            # the registry may be invalidated during the yield
            registry_invalidated += cr.transaction._registry_invalidated

        # simulate cr.commit() again to flush changes made by the main cursor
        state_stack = cr.transaction._state_stack__
        closing = cr._closing

        cr._closing = False  # do a reset
        cr.transaction._state_stack__ = []  # replace the stack
        with cr.transaction.committing():
            pass  # no real commit
    finally:
        cr.transaction._state_stack__ = state_stack
        cr._closing = closing
        cr.transaction._registry_invalidated = registry_invalidated


class TransactionCase(BaseCase):
    """ Test class in which all test methods are run in a single transaction,
    but each test method is run in a sub-transaction managed by a savepoint.
    The transaction's cursor is always closed without committing.

    The data setup common to all methods should be done in the class method
    `setUpClass`, so that it is done once for all test methods. This is useful
    for test cases containing fast tests but with significant database setup
    common to all cases (complex in-db test data).

    After being run, each test method cleans up the record cache and the
    registry cache. However, there is no cleanup of the registry models and
    fields. If a test modifies the registry (custom models and/or fields), it
    should prepare the necessary cleanup (`self.env.transaction.will_change_registry()`).
    """
    muted_registry_logger = mute_logger(odoo.orm.models.registry._logger.name)
    freeze_time = None
    savepoint = None

    @classmethod
    def _gc_filestore(cls):
        # attachment can be created or unlink during the tests.
        # they can addup during test and take some disc space.
        # since cron are not running during tests, we need to gc manually
        # We need to check the status of the file system outside of the test cursor
        with cls.registry.cursor() as cr:
            gc_env = api.Environment(cr, api.SUPERUSER_ID, {})
            gc_env['ir.attachment']._gc_file_store_unsafe(grace_period=0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())

        def signal_changes(cr, names):
            if 'registry' in names:
                if not cls.registry.ready:
                    _logger.info('Skipping signal changes during tests')
                    return
                _logger.info('Simulating signal changes during tests')
                cls.registry.registry_sequence += 1
                for key, (seq, data) in cls.registry.registry_caches__.items():
                    cls.registry.registry_caches__[key] = (seq + 1, {})
            elif names:
                _logger.debug('Simulating signal changes during tests')
                for name in names:
                    cls.registry.registry_caches__[name] = (cls.registry.registry_caches__[name][0] + 1, {})

        def get_sequences(cr):
            return cls.registry.registry_sequence, {name: val[0] for name, val in cls.registry.registry_caches__.items()}

        def reset_registry(registry, *, registry_sequence, caches):
            registry.registry_sequence = registry_sequence
            registry.registry_caches__ = caches

        cls.addClassCleanup(
            reset_registry, cls.registry,
            registry_sequence=cls.registry.registry_sequence,
            caches=cls.registry.registry_caches__.copy(),
        )

        cls.startClassPatcher(patch.object(cls.registry, '_signal_changes', signal_changes))
        cls.startClassPatcher(patch.object(cls.registry, 'get_sequences', get_sequences))
        cls.addClassCleanup(cls._gc_filestore)

        cls.cr = cls.registry.cursor()
        cls.addClassCleanup(typing.cast('Cursor', cls.cr).close)

        def check_cursor_stack():
            for cursor in test_cursor.TestCursor._cursors_stack:
                _logger.info('One curor was remaining in the TestCursor stack at the end of the test')
                cursor._closed = True
            test_cursor.TestCursor._cursors_stack = []

        cls.addClassCleanup(check_cursor_stack)

        if cls.freeze_time:
            cls.startClassPatcher(cls.freeze_time)

        def forbidden(*args, **kwars):
            traceback.print_stack()
            raise AssertionError('Cannot commit or rollback a cursor from inside a test, this will lead to a broken cursor when trying to rollback the test. Please rollback to a specific savepoint instead or open another cursor if really necessary')

        cls.commit_patcher = patch.object(cls.cr, 'commit', forbidden)
        cls.startClassPatcher(cls.commit_patcher)
        cls.rollback_patcher = patch.object(cls.cr, 'rollback', forbidden)
        cls.startClassPatcher(cls.rollback_patcher)
        cls.close_patcher = patch.object(cls.cr, 'close', forbidden)
        cls.startClassPatcher(cls.close_patcher)

        cls.env = api.Environment(cls.cr, api.SUPERUSER_ID, {})
        cls.env.transaction._wrote__ = True  # isolate tests: avoid propagating cache on rollback

        # speedup CryptContext. Many password-type logins are done during tests, avoid spending time hashing password with many rounds
        def _crypt_context(self):  # noqa: ARG001
            cryptCtx = CryptContext(
                ['pbkdf2_sha512', 'plaintext'],
                pbkdf2_sha512__rounds=1,
            )
            # The modified hash configuration causes rotation of the in-database password hash values.
            # Rotating password hashes mid-test causes session_id rotation leading into indeterministic 'user not logged in' errors.
            # Never returning a replacement hash prevents this problem.
            original_verify_and_update = cryptCtx.verify_and_update

            def mock_verify_and_update(*args, **kwargs):
                valid, replacement_hash = original_verify_and_update(*args, **kwargs)
                if replacement_hash:
                    _logger.info("Surpressing hash update in CryptContext override")
                return valid, None

            cryptCtx.verify_and_update = mock_verify_and_update
            return cryptCtx

        cls._crypt_context_patcher = patch('odoo.addons.base.models.res_users.ResUsersPatchedInTest._crypt_context', _crypt_context)
        cls.startClassPatcher(cls._crypt_context_patcher)

    def setUp(self):
        super().setUp()

        def reset_registry(registry, *, registry_sequence, caches):
            registry.registry_sequence = registry_sequence
            registry.registry_caches__ = caches

        self.addCleanup(
            # for flushing cursor
            reset_registry, self.registry,
            registry_sequence=self.registry.registry_sequence,
            caches=self.registry.registry_caches__.copy(),
        )

        def _check_registry_lock():
            if _registry_test_lock.count == 0:
                _logger.warning('The registry test lock is still released at the end of %s', self.canonical_tag)
            elif _registry_test_lock.count > 1:
                _logger.warning(
                    'The registry test lock was acquired more than once (%s) at the end of %s',
                    _registry_test_lock.count, self.canonical_tag,
                )

        self.addCleanup(_check_registry_lock)

        # flush everything in setUpClass before introducing a savepoint
        cr = self.cr
        if self.savepoint is None:
            # create savepoint, and close it at class cleanup
            sp = self.cr.savepoint(flush=True)
            self.addClassCleanup(sp.close, rollback=False)
            # store savepoint on the class (to be shared across all test instances)
            self.__class__.savepoint = sp
            self.addClassCleanup(setattr, self.__class__, 'savepoint', None)

        # This prevents precommit functions and data from piling up
        # until cr.flush is called in 'assertRaises' clauses
        def _reset(cb, funcs, data):
            cb._funcs = funcs
            cb.data = data
        for callback in [cr.precommit, cr.postcommit, cr.prerollback, cr.postrollback]:
            self.addCleanup(_reset, callback, deque(callback._funcs), deepcopy(callback.data))

        self.addCleanup(self.savepoint.rollback)

        # To keep tests isolated, add a CacheLayer.
        # - L1: cursor cache
        # - L2: savepoint cache
        # - L3: this isolation layer
        # flushing_cursor() may push data from the current to the parent layer
        # (from L3 to L2) and we need L1 to be unaffected by tests.
        transaction = self.env.transaction
        for name, layer in transaction.ormcaches__.items():
            transaction.ormcaches__[name] = CacheLayer(layer)

    @classmethod
    @contextmanager
    def mock_datetime_and_now(cls, mock_dt):
        """ Used when synchronization date (using env.cr.now()) is important
        in addition to standard datetime mocks. Used mainly to detect sync
        issues. """
        mock_dt = fields.Datetime.to_datetime(mock_dt)
        with freeze_time(mock_dt) as frozen_datetime_mock, \
             patch.object(cls.env.cr, 'now', lambda: mock_dt):
            cls.frozen_datetime_mock = frozen_datetime_mock
            yield

    @classmethod
    @contextmanager
    def registry_test_mode(cls, *, cr: Cursor | None = None, registry: Registry | None = None):
        if cr is None:
            cr = cls.cr
        with flushing_cursor(cr), super().registry_test_mode(cr=cr, registry=registry):
            yield

    @typing.final
    def enter_registry_test_mode(self):  # deprecated: alias for registry_test_mode
        return self.registry_test_mode()

    @contextmanager
    def allow_pdf_render(self):
        """
        Allows the pdf renderer to send requests to the backend.
        Enters registry mode if necessary.
        """
        with ExitStack() as stack:
            if not type(self)._registry_patched:
                stack.enter_context(self.registry_test_mode())

            case_instance = self

            def _patched_run_wkhtmltopdf(self, args):
                with (
                    patch.object(case_instance, 'http_request_key', 'wkhtmltopdf'),
                    release_test_lock(),
                    patch('odoo.tests.common.transaction._disable_flushing_cursor', True),
                ):
                    args = ['--cookie', TEST_CURSOR_COOKIE_NAME, 'wkhtmltopdf', *args]
                    return old_run_wkhtmltopdf(self, args)

            report_model = self.env.registry['ir.actions.report']
            try:
                old_run_wkhtmltopdf = report_model._run_wkhtmltopdf
            except AttributeError:
                pass
            else:
                stack.enter_context(
                    patch.object(report_model, '_run_wkhtmltopdf', _patched_run_wkhtmltopdf),
                )
            yield

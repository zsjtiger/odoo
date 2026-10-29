"""The base test case: the setup of the tests, the environment and the references of the records, and the cross-module test case."""

from __future__ import annotations

import inspect
import sys
import typing
from unittest.mock import _patch, patch
from urllib.parse import urlsplit
import psutil
import requests
from lxml import etree, html
from requests import PreparedRequest, Session
import odoo.cli
import odoo.models
from odoo import api
from odoo.modules.registry import Registry
from odoo.orm.database.sql_db import Cursor
from odoo.tools import file_open
from odoo.tools.files.binary import BinaryBytes
from odoo.tests import case
from ..utils import DISABLE_TIMEOUTS, HOST, _logger
from ..mocks import BlockedRequest, _super_send

if typing.TYPE_CHECKING:
    from collections.abc import Iterable


class BaseCase(case.TestCase):
    """ Subclass of TestCase for Odoo-specific code. This class is abstract and
    expects self.registry, self.cr and self.uid to be initialized by subclasses.
    """
    registry: Registry = None
    env: api.Environment = None
    cr: Cursor = None
    longMessage = True      # more verbose error message by default: https://www.odoo.com/r/Vmh
    warm = True             # False during warm-up phase (see :func:`warmup`)
    _python_version = sys.version_info
    _registry_patched = False
    _registry_readonly_enabled = True
    test_cursor_lock_timeout: int = 3600 if DISABLE_TIMEOUTS else 20
    @classmethod
    def __init_subclass__(cls):
        """Assigns default test tags ``standard`` and ``post_install`` to test
        cases not having them. Also sets a completely unnecessary
        ``test_module`` attribute.
        """
        super().__init_subclass__()
        if cls.__module__.startswith('odoo.addons.'):
            if getattr(cls, 'test_tags', None) is None:
                cls.test_tags = {'standard', 'post_install'}
            cls.test_module = cls.__module__.split('.')[2]
    def __init__(self, methodName='runTest'):
        super().__init__(methodName)
        self.addTypeEqualityFunc(etree._Element, self.assertTreesEqual)
        self.addTypeEqualityFunc(html.HtmlElement, self.assertTreesEqual)
        if methodName != 'runTest':
            self.test_tags = self.test_tags | set(self.get_method_additional_tags(getattr(self, methodName)))
    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        # allow localhost requests
        # TODO: also check port?
        url = urlsplit(r.url)
        timeout = kw.get('timeout')
        if timeout and timeout < 10:
            _logger.getChild('requests').info('request %s with timeout %s increased to 10s during tests', url, timeout)
            kw['timeout'] = 10
        if url.hostname in (HOST, 'localhost'):
            return _super_send(s, r, **kw)
        if url.scheme == 'file':
            return _super_send(s, r, **kw)

        _logger.getChild('requests').info(
            "Blocking un-mocked external HTTP request %s %s", r.method, r.url)
        raise BlockedRequest(f"External requests verboten (was {r.method} {r.url})")
    @classmethod
    def setUpClass(cls):
        def check_remaining_processes():
            current_process = psutil.Process()
            children = current_process.children(recursive=False)
            for child in children:
                _logger.warning('A child process was found, terminating it: %s', child)
                child.terminate()
            psutil.wait_procs(children, timeout=10)  # mainly to avoid a zombie process that would be logged again at the end.
        cls.addClassCleanup(check_remaining_processes)

        def check_remaining_patchers():
            for patcher in _patch._active_patches:
                _logger.warning("A patcher (targeting %s.%s) was remaining active at the end of %s, disabling it...", patcher.target, patcher.attribute, cls.__name__)
                patcher.stop()
        cls.addClassCleanup(check_remaining_patchers)
        super().setUpClass()
        if 'standard' in cls.test_tags or 'click_all' in cls.test_tags:
            # if the method is passed directly `patch` discards the session
            # object which we need
            # pylint: disable=unnecessary-lambda
            patcher = patch.object(
                requests.sessions.Session,
                'send',
                lambda s, r, **kwargs: cls._request_handler(s, r, **kwargs),
            )
            patcher.start()
            cls.addClassCleanup(patcher.stop)

        # cannot create new registries during testing, it would mess up test
        # runs, install other modules, reporting, etc.
        def forbidden(*a, **kw):
            raise RuntimeError("cannot call Registry.new during testing")
        cls.startClassPatcher(patch.object(Registry, 'new', forbidden))
    def setUp(self):
        super().setUp()
        self.http_request_key: str = ''
        self.http_request_allow_all: bool = False
    def cursor(self):
        return self.registry.cursor()
    @property
    def uid(self):
        """ Get the current uid. """
        return self.env.uid
    @uid.setter
    def uid(self, user):
        """ Set the uid by changing the test's environment. """
        self.env = self.env(user=user)
        # set the updated environment as the default one
        self.env.transaction.default_env = self.env
    def ref(self, xid):
        """ Returns database ID for the provided :term:`external identifier`,
        shortcut for ``_xmlid_lookup``

        :param xid: fully-qualified :term:`external identifier`, in the form
                    :samp:`{module}.{identifier}`
        :raise: ValueError if not found
        :returns: registered id
        """
        return self.browse_ref(xid).id
    def browse_ref(self, xid):
        """ Returns a record object for the provided
        :term:`external identifier`

        :param xid: fully-qualified :term:`external identifier`, in the form
                    :samp:`{module}.{identifier}`
        :raise: ValueError if not found
        :returns: :class:`~odoo.models.BaseModel`
        """
        assert "." in xid, "this method requires a fully qualified parameter, in the following form: 'module.identifier'"
        return self.env.ref(xid)
    def patch(self, obj, key, val):
        return _patching.patch(self, obj, key, val)
    @classmethod
    def classPatch(cls, obj, key, val):
        return _patching.classPatch(cls, obj, key, val)
    def startPatcher(self, patcher):
        return _patching.startPatcher(self, patcher)
    @classmethod
    def startClassPatcher(cls, patcher):
        return _patching.startClassPatcher(cls, patcher)
    def enterContext(self, cm):
        return _patching.enterContext(self, cm)
    @classmethod
    def enterClassContext(cls, cm):
        return _patching.enterClassContext(cls, cm)
    def with_user(self, login):
        return _patching.with_user(self, login)
    def debug_mode(self):
        return _patching.debug_mode(self)
    def _raisesContext(self, method, expected_exception, *args, **kwargs):
        return _asserts._raisesContext(self, method, expected_exception, *args, **kwargs)
    def assertRaises(self, expected_exception, callable=None, *args, **kwargs):
        return _asserts.assertRaises(self, expected_exception, callable, *args, **kwargs)
    def assertRaisesRegex(self, expected_exception, expected_regex, callable=None, *args, **kwargs):
        return _asserts.assertRaisesRegex(self, expected_exception, expected_regex, callable, *args, **kwargs)
    def _patchExecute(self, actual_queries, flush=True):
        return _asserts._patchExecute(self, actual_queries, flush)
    def assertQueries(self, expected, flush=True):
        return _asserts.assertQueries(self, expected, flush)
    def assertQueryCount(self, default=0, flush=True, **counters):
        return _asserts.assertQueryCount(self, default, flush, **counters)
    def assertRecordValues(self, records: odoo.models.BaseModel, expected_values: list[dict], *, field_names: Iterable[str] | None=None) -> None:
        return _asserts.assertRecordValues(self, records, expected_values, field_names=field_names)
    def assertItemsEqual(self, a, b, msg=None):
        return _asserts.assertItemsEqual(self, a, b, msg)
    def assertTreesEqual(self, n1, n2, msg=None):
        return _asserts.assertTreesEqual(self, n1, n2, msg)
    def _assertXMLEqual(self, original, expected, parser='xml'):
        return _asserts._assertXMLEqual(self, original, expected, parser)
    def assertXMLEqual(self, original, expected):
        return _asserts.assertXMLEqual(self, original, expected)
    def assertHTMLEqual(self, original, expected):
        return _asserts.assertHTMLEqual(self, original, expected)
    def profile(self, description='', **kwargs):
        return _patching.profile(self, description, **kwargs)
    @classmethod
    def file_read(cls, path: str) -> BinaryBytes:
        """Read contents of a file using ``file_open``."""
        with file_open(path, 'rb') as f:
            return BinaryBytes(f.read())
    @classmethod
    def registry_test_mode(cls, *, cr: Cursor | None=None, registry: Registry | None=None):
        return _modes.registry_test_mode(cls, cr=cr, registry=registry)
    @classmethod
    def set_registry_readonly_mode(cls, enabled: bool):
        return _modes.set_registry_readonly_mode(cls, enabled)
    def assertCanOpenTestCursor(self):
        return _modes.assertCanOpenTestCursor(self)
    def get_method_additional_tags(self, test_method):
        """Guess if the test_methods is a query_count and adds an `is_query_count` tag on the test
        """
        additional_tags = []
        if odoo.tools.config['test_tags'] and 'is_query_count' in odoo.tools.config['test_tags']:
            method_source = inspect.getsource(test_method) if test_method else ''
            if 'self.assertQueryCount' in method_source:
                additional_tags.append('is_query_count')
        return additional_tags


class CrossModule(case.TestCase):
    _cross_module = True
    _test_modules = []

    def _callTestMethod(self, method):
        method(self._test_modules)

    def _get_canonical_tags_params(self, log=None):
        result = super()._get_canonical_tags_params(log)
        result['module'] = None
        return result


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import asserts as _asserts, patching as _patching, modes as _modes  # noqa: E402

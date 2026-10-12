# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Base test case, with the assertion helpers and the test data helpers."""

from __future__ import annotations

import difflib
import inspect
import logging
import pprint
import re
import sys
import typing
from contextlib import ExitStack, contextmanager
from functools import partial
from itertools import zip_longest
from unittest.mock import Mock, _patch, patch
from urllib.parse import urlsplit
import psutil
import requests
from lxml import etree, html
from requests import PreparedRequest, Session
from werkzeug.exceptions import BadRequest
import odoo.cli
import odoo.models
import odoo.orm.models.registry
from odoo import api
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.http import request, request_var
from odoo.http.session import (
    get_default_session,
)
from odoo.modules.registry import Registry
from odoo.orm.database.sql_db import Cursor
from odoo.tools import SQL, DotDict, file_open, float_compare
from odoo.tools.profiling import profiler
from odoo.tools.files.binary import BinaryBytes
from odoo.tools.mail import single_email_re
from odoo.tools.misc import diff_zip
import odoo.addons.base
from odoo.tests import case, test_cursor

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

from .utils import DISABLE_TIMEOUTS, HOST, TEST_CURSOR_COOKIE_NAME, _logger
from .mocks import BlockedRequest, _super_send
from .locks import DummyRLock, _registry_test_lock

def new_test_user(env, login='', groups='base.group_user', context=None, **kwargs):
    """ Helper function to create a new test user. It allows to quickly create
    users given its login and groups (being a comma separated list of xml ids).
    Kwargs are directly propagated to the create to further customize the
    created user.

    User creation uses a potentially customized environment using the context
    parameter allowing to specify a custom context. It can be used to force a
    specific behavior and/or simplify record creation. An example is to use
    mail-related context keys in mail tests to speedup record creation.

    Some specific fields are automatically filled to avoid issues

     * group_ids: it is filled using groups function parameter;
     * name: "login (groups)" by default as it is required;
     * email: it is either the login (if it is a valid email) or a generated
       string 'x.x@example.com' (x being the first login letter). This is due
       to email being required for most odoo operations;
    """
    if not login:
        raise ValueError('New users require at least a login')
    if not groups:
        raise ValueError('New users require at least user groups')
    if context is None:
        context = {}

    group_ids = [Command.set(kwargs.pop('group_ids', False) or [env.ref(g.strip()).id for g in groups.split(',')])]
    create_values = dict(kwargs, login=login, group_ids=group_ids)
    # automatically generate a name as "Login (groups)" to ease user comprehension
    if not create_values.get('name'):
        create_values['name'] = '%s (%s)' % (login, groups)
    # automatically give a password equal to login
    if not create_values.get('password'):
        create_values['password'] = login + 'x' * (8 - len(login))
    # generate email if not given as most test require an email
    if 'email' not in create_values:
        if single_email_re.match(login):
            create_values['email'] = login
        else:
            create_values['email'] = '%s.%s@example.com' % (login[0], login[0])
    # ensure company_id + allowed company constraint works if not given at create
    if 'company_id' in create_values and 'company_ids' not in create_values:
        create_values['company_ids'] = [(4, create_values['company_id'])]

    return env['res.users'].sudo().with_context(**context).create(create_values)


def loaded_demo_data(env):
    return bool(env.ref('base.user_demo', raise_if_not_found=False))


class RecordCapturer:
    def __init__(self, model, domain=None):
        self._model = model
        self._domain = domain or []

    def __enter__(self):
        self._before = self._model.search(self._domain, order='id')
        self._after = None
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if exc_type is None:
            self._after = self._model.search(self._domain, order='id') - self._before

    @property
    def records(self):
        if self._after is None:
            return self._model.search(self._domain, order='id') - self._before
        return self._after


def _enter_context(cm, addcleanup):
    # We look up the special methods on the type to match the with
    # statement.
    cls = type(cm)
    try:
        enter = cls.__enter__
        exit = cls.__exit__
    except AttributeError:
        raise TypeError(f"'{cls.__module__}.{cls.__qualname__}' object does "
                        f"not support the context manager protocol") from None
    result = enter(cm)
    addcleanup(exit, cm, None, None, None)
    return result


def _normalize_arch_for_assert(arch_string, parser_method="xml"):
    """Takes some xml and normalize it to make it comparable to other xml
    in particular, blank text is removed, and the output is pretty-printed

    :param str arch_string: the string representing an XML arch
    :param str parser_method: an string representing which lxml.Parser class to use
        when normalizing both archs. Takes either "xml" or "html"
    :return: the normalized arch
    :rtype str:
    """
    Parser = None
    if parser_method == 'xml':
        Parser = etree.XMLParser
    elif parser_method == 'html':
        Parser = etree.HTMLParser
    parser = Parser(remove_blank_text=True)
    arch_string = etree.fromstring(arch_string, parser=parser)
    return etree.tostring(arch_string, pretty_print=True, encoding='unicode')


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
        """ Do the patch ``setattr(obj, key, val)``, and prepare cleanup. """
        patcher = patch.object(obj, key, val)   # this is unittest.mock.patch
        patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def classPatch(cls, obj, key, val):
        """ Do the patch ``setattr(obj, key, val)``, and prepare cleanup. """
        patcher = patch.object(obj, key, val)   # this is unittest.mock.patch
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def startPatcher(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @classmethod
    def startClassPatcher(cls, patcher):
        mock = patcher.start()
        cls.addClassCleanup(patcher.stop)
        return mock

    def enterContext(self, cm):
        """Enters the supplied context manager.

        If successful, also adds its __exit__ method as a cleanup
        function and returns the result of the __enter__ method.
        """
        return _enter_context(cm, self.addCleanup)

    @classmethod
    def enterClassContext(cls, cm):
        """Same as enterContext, but class-wide."""
        return _enter_context(cm, cls.addClassCleanup)

    @contextmanager
    def with_user(self, login):
        """ Change user for a given test, like with self.with_user() ... """
        old_uid = self.uid
        old_env = self.env
        try:
            user = self.env['res.users'].sudo().search([('login', '=', login)], order='login')
            assert user, "Login %s not found" % login
            # switch user
            self.uid = user.id
            self.env = self.env(user=self.uid)
            yield
        finally:
            # back
            self.uid = old_uid
            self.env = old_env

    @contextmanager
    def debug_mode(self):
        """ Enable the effects of debug mode (in particular for group ``base.group_no_one``). """
        request = Mock(
            httprequest=Mock(host='localhost'),
            db=self.env.cr.dbname,
            env=self.env,
            session=DotDict(get_default_session(), debug='1', sid=''),
        )
        reset_req = None
        try:
            self.env.flush_all()
            self.env.invalidate_all()
            reset_req = request_var.set(request)
            yield
            self.env.flush_all()
            self.env.invalidate_all()
        finally:
            current_request = request_var.get()
            if reset_req is not None:
                request_var.reset(reset_req)
            if current_request is not request:
                raise Exception('Wrong request stack cleanup.')

    @contextmanager
    def _raisesContext(self, method, expected_exception, *args, **kwargs):
        """ Context manager that clears the environment upon failure. """
        with ExitStack() as init:
            if self.env:
                init.enter_context(self.env.cr.savepoint())
                if isinstance(expected_exception, tuple):
                    clear_cache = any(issubclass(e, AccessError) for e in expected_exception)
                else:
                    clear_cache = issubclass(expected_exception, AccessError)
                if clear_cache:
                    # When checking for an `AccessError`, the cache is cleared
                    # before executing the code. This avoids cache pollution issues and
                    # ensures that access are re-evaluated correctly.
                    self.env.transaction.clear()

            with ExitStack() as inner:
                cm = inner.enter_context(method(expected_exception, *args, **kwargs))
                # *moves* the cleanups from init to inner, this ensures the
                # savepoint gets rolled back when `yield` raises `exception`,
                # but still allows the initialisation to be protected *and* not
                # interfered with by `assertRaises`.
                inner.push(init.pop_all())

                yield cm

    def assertRaises(self, expected_exception, callable=None, *args, **kwargs):
        if callable:
            with self._raisesContext(super().assertRaises, expected_exception):
                callable(*args, **kwargs)
            return None
        return self._raisesContext(super().assertRaises, expected_exception, *args, **kwargs)

    def assertRaisesRegex(self, expected_exception, expected_regex, callable=None, *args, **kwargs):
        if callable:
            with self._raisesContext(super().assertRaisesRegex, expected_exception, expected_regex):
                callable(*args, **kwargs)
            return None
        return self._raisesContext(super().assertRaisesRegex, expected_exception, expected_regex, *args, **kwargs)

    def _patchExecute(self, actual_queries, flush=True):
        Cursor_execute = Cursor.execute

        def execute(self, query, params=None, log_exceptions=None):
            if isinstance(query, SQL):
                assert params is None
                query, params, _ = query._sql_tuple
            actual_queries.append(query)
            return Cursor_execute(self, query, params, log_exceptions)

        if flush:
            self.env.cr.flush()

        with (
            patch('odoo.orm.database.sql_db.Cursor.execute', execute),
            patch.object(self.env.registry, 'unaccent', lambda x: x),
        ):
            yield actual_queries
            if flush:
                self.env.cr.flush()

    @contextmanager
    def assertQueries(self, expected, flush=True):
        """ Check the queries made by the current cursor. ``expected`` is a list
        of strings representing the expected queries being made. Query strings
        are matched against each other, ignoring case and whitespaces. Moreover,
        the substring ``"..."`` can be used as a wildcard to match anything in
        the corresponding actual query.
        """
        actual_queries = []

        yield from self._patchExecute(actual_queries, flush)

        if not self.warm:
            return

        # diff lists of queries 'expected' and 'actual_queries'
        queries1 = [QueryLike(query) for query in expected]
        queries2 = [QueryLike(query) for query in actual_queries]
        if queries1 == queries2:
            return

        diff = "\n".join(
            (f"--- {query1}" if query2 is None else
             f"+++ {query2}" if query1 is None else
             f"=== {query2}")
            for query1, query2 in diff_zip(queries1, queries2)
        )
        self.fail(self._formatMessage("\n" + diff, "Not the expected queries"))

    @contextmanager
    def assertQueryCount(self, default=0, flush=True, **counters):
        """ Context manager that counts queries. It may be invoked either with
            one value, or with a set of named arguments like ``login=value``::

                with self.assertQueryCount(42):
                    ...

                with self.assertQueryCount(admin=3, demo=5):
                    ...

            The second form is convenient when used with :func:`users`.
        """
        flush_func = self.env.cr.flush if flush else lambda: None
        if self.warm:
            # mock random in order to avoid random bus gc
            with patch('random.random', lambda: 1):
                login = self.env.user.login
                expected = counters.get(login, default)
                flush_func()
                count0 = self.cr.sql_log_count
                yield
                flush_func()
                count = self.cr.sql_log_count - count0
                if count != expected:
                    # add some info on caller to allow semi-automatic update of query count
                    _frame, filename, linenum, funcname, _lines, _index = inspect.stack()[2]
                    filename = filename.replace('\\', '/')
                    if "/odoo/addons/" in filename:
                        filename = filename.rsplit("/odoo/addons/", 1)[1]
                    if count > expected:
                        msg = "Query count more than expected for user %s: %d > %d in %s at %s:%s"
                        # add a subtest in order to continue the test_method in case of failures
                        with self.subTest():
                            self.fail(msg % (login, count, expected, funcname, filename, linenum))
                    elif expected and not count:
                        msg = "Query count did not detect any queries %s: expected %d in %s at %s:%s"
                        with self.subTest():
                            self.fail(msg % (login, expected, funcname, filename, linenum))
                    else:
                        logger = logging.getLogger(type(self).__module__)
                        msg = "Query count less than expected for user %s: %d < %d in %s at %s:%s"
                        logger.info(msg, login, count, expected, funcname, filename, linenum)
        else:
            # flush before and after during warmup, in order to reproduce the
            # same operations, otherwise the caches might not be ready!
            flush_func()
            yield
            flush_func()

    def assertRecordValues(
            self,
            records: odoo.models.BaseModel,
            expected_values: list[dict],
            *,
            field_names: Iterable[str] | None = None,
    ) -> None:
        ''' Compare a recordset with a list of dictionaries representing the expected results.
        This method performs a comparison element by element based on their index.
        Then, the order of the expected values is extremely important.

        .. note::

            - ``None`` expected values can be used for empty fields.
            - x2many fields are expected by ids (so the expected value should be
              a ``list[int]``
            - many2one fields are expected by id (so the expected value should
              be an ``int``

        :param records: The records to compare.
        :param expected_values: Items to check the ``records`` against.
        :param field_names: list of fields to check during comparison, if
                            unspecified all expected_values must have the same
                            keys and all are checked
        '''
        if not field_names:
            field_names = expected_values[0].keys()
            for i, v in enumerate(expected_values):
                self.assertEqual(
                    v.keys(), field_names,
                    f"All expected values must have the same keys, found differences between records 0 and {i}",
                )

        expected_reformatted = []
        for vs in expected_values:
            r = {}
            for f in field_names:
                t = records._fields[f].type
                if t in ('one2many', 'many2many'):
                    r[f] = sorted(vs[f])
                elif t == 'float':
                    r[f] = float(vs[f])
                elif t == 'integer':
                    r[f] = int(vs[f])
                elif t == 'binary':
                    r[f] = bytes(vs[f])
                elif vs[f] is None:
                    r[f] = False
                else:
                    r[f] = vs[f]
            expected_reformatted.append(r)

        record_reformatted = []
        for record in records:
            r = {}
            for field_name in field_names:
                record_value = record[field_name]
                match record._fields[field_name]:
                    case odoo.fields.Many2one():
                        record_value = record_value.id
                    case odoo.fields.One2many() | odoo.fields.Many2many():
                        record_value = sorted(record_value.ids)
                    case odoo.fields.Float() as field if digits := field.get_digits(record.env):
                        record_value = Approx(record_value, digits[1], decorate=False)
                    case odoo.fields.Monetary() as field if currency_field_name := field.get_currency_field(record):
                        # don't round if there's no currency set
                        if c := record[currency_field_name]:
                            record_value = Approx(record_value, c, decorate=False)
                    case odoo.fields.Binary() as field:
                        record_value = record_value.content

                r[field_name] = record_value
            record_reformatted.append(r)

        try:
            self.assertSequenceEqual(expected_reformatted, record_reformatted, seq_type=list)
            return
        except AssertionError as e:
            standardMsg, _, diffMsg = str(e).rpartition('\n')
            if 'self.maxDiff' not in diffMsg:
                raise
            # move out of handler to avoid exception chaining

        diffMsg = "".join(difflib.unified_diff(
            pprint.pformat(expected_reformatted).splitlines(keepends=True),
            pprint.pformat(record_reformatted).splitlines(keepends=True),
            fromfile="expected", tofile="records",
        ))
        self.fail(self._formatMessage(None, standardMsg + '\n' + diffMsg))

    # turns out this thing may not be quite as useful as we thought...
    def assertItemsEqual(self, a, b, msg=None):
        self.assertCountEqual(a, b, msg=None)

    def assertTreesEqual(self, n1, n2, msg=None):
        self.assertIsNotNone(n1, msg)
        self.assertIsNotNone(n2, msg)
        self.assertEqual(n1.tag, n2.tag, msg)
        # Because lxml.attrib is an ordereddict for which order is important
        # to equality, even though *we* don't care
        self.assertEqual(dict(n1.attrib), dict(n2.attrib), msg)
        self.assertEqual((n1.text or u'').strip(), (n2.text or u'').strip(), msg)
        self.assertEqual((n1.tail or u'').strip(), (n2.tail or u'').strip(), msg)

        for c1, c2 in zip_longest(n1, n2):
            self.assertTreesEqual(c1, c2, msg)

    def _assertXMLEqual(self, original, expected, parser="xml"):
        """Asserts that two xmls archs are equal

        :param original: the xml arch to test
        :type original: str
        :param expected: the xml arch of reference
        :type expected: str
        :param parser: an string representing which lxml.Parser class to use
            when normalizing both archs. Takes either "xml" or "html"
        :type parser: str
        """
        self.maxDiff = 10000
        if original:
            original = _normalize_arch_for_assert(original, parser)
        if expected:
            expected = _normalize_arch_for_assert(expected, parser)
        self.assertEqual(original, expected)

    def assertXMLEqual(self, original, expected):
        return self._assertXMLEqual(original, expected)

    def assertHTMLEqual(self, original, expected):
        return self._assertXMLEqual(original, expected, 'html')

    def profile(self, description='', **kwargs):
        test_method = getattr(self, '_testMethodName', 'Unknown test method')
        if not hasattr(self, 'profile_session'):
            self.profile_session = profiler.make_session(test_method)
        if 'db' not in kwargs:
            kwargs['db'] = self.env.cr.dbname
        return profiler.Profiler(
            description='%s uid:%s %s %s' % (test_method, self.env.user.id, 'warm' if self.warm else 'cold', description),
            profile_session=self.profile_session,
            **kwargs)

    @classmethod
    def file_read(cls, path: str) -> BinaryBytes:
        """Read contents of a file using ``file_open``."""
        with file_open(path, 'rb') as f:
            return BinaryBytes(f.read())

    @classmethod
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

    @classmethod
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


class Like:
    """
        A string-like object comparable to other strings but where the substring
        '...' can match anything in the other string.

        Example of usage:

            self.assertEqual("SELECT field1, field2, field3 FROM model", Like('SELECT ... FROM model'))
            self.assertIn(Like('Company ... (SF)'), ['TestPartner', 'Company 8 (SF)', 'SomeAdress'])
            self.assertEqual([
                'TestPartner',
                'Company 8 (SF)',
                'Anything else'
            ], [
                'TestPartner',
                Like('Company ... (SF)'),
                Like('...'),
            ])

        In case of mismatch, here is an example of error message

            AssertionError: Lists differ: ['TestPartner', 'Company 8 (LA)', 'Anything else'] != ['TestPartner', ~Company ... (SF), ~...]

            First differing element 1:
            'Company 8 (LA)'
            ~Company ... (SF)~

            - ['TestPartner', 'Company 8 (LA)', 'Anything else']
            + ['TestPartner', ~Company ... (SF), ~...]


        """
    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = '.*'.join([re.escape(part.strip()) for part in self.pattern.split('...')])

    def __eq__(self, other):
        return re.fullmatch(self.regex, other.strip(), re.DOTALL)

    def __repr__(self):
        return repr(self.pattern)


class QueryLike(str):
    """ Wrapper for comparing query strings. The comparison ignores case and
    spaces, and the substring ``"..."`` can match anything on the right-hand
    side of operator `==`.
    """
    __slots__ = ('_regex', '_stripped')

    def __init__(self, value):
        # ignore case and spaces when comparing
        self._stripped = "".join(value.lower().split())
        # "..." matches anything
        self._regex = ".*".join(re.escape(part) for part in self._stripped.split('...'))

    def __hash__(self):
        return hash(self._stripped)

    def __eq__(self, other):
        if not isinstance(other, QueryLike):
            return NotImplemented
        return re.fullmatch(self._regex, other._stripped, re.DOTALL)


class WhitespaceInsensitive(str):
    __slots__ = ()

    def __hash__(self):
        return hash(re.sub(r'\s+', ' ', self))

    def __eq__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return re.sub(r'\s+', ' ', self) == re.sub(r'\s+', ' ', other)


class Approx:  # noqa: PLW1641
    """A wrapper for approximate float comparisons. Uses float_compare under
    the hood.

    Most of the time, :meth:`TestCase.assertAlmostEqual` is more useful, but it
    doesn't work for all helpers.
    """
    def __init__(self, value: float, rounding: int | float | odoo.addons.base.models.res_currency.ResCurrency, /, decorate: bool) -> None:  # noqa: PYI041
        self.value = value
        self.decorate = decorate
        if isinstance(rounding, int):
            self.cmp = partial(float_compare, precision_digits=rounding)
        elif isinstance(rounding, float):
            self.cmp = partial(float_compare, precision_rounding=rounding)
        else:
            self.cmp = rounding.compare_amounts

    def __repr__(self) -> str:
        if self.decorate:
            return f"~{self.value!r}"
        return repr(self.value)

    def __eq__(self, other: object) -> bool | NotImplemented:
        if not isinstance(other, (float, int)):
            return NotImplemented
        return self.cmp(self.value, other) == 0

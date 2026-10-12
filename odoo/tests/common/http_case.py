# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""HTTP test case: the requests to the server, the XML-RPC and JSON-RPC transports."""

from __future__ import annotations

import base64
import contextlib
import inspect
import itertools
import json
import logging
import os
import threading
import time
import typing
from contextlib import ExitStack, contextmanager
from textwrap import shorten
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4
from xmlrpc import client as xmlrpclib
import requests
from requests import Session
import odoo.cli
import odoo.models
import odoo.orm.models.registry
from odoo import api
from odoo.http import request
from odoo.http.requestlib import Request
from odoo.http.session import (
    DEFAULT_LANG,
    get_default_session,
    logout,
    update_session_token,
    session_store,
)
from odoo.http.session import Session as OdooHttpSession
from odoo.tools import config
from odoo.tools.profiling import profiler
from odoo.tools.misc import real_time
import odoo.addons.base

if typing.TYPE_CHECKING:
    pass

from .utils import DEFAULT_SUCCESS_SIGNAL, DISABLE_TIMEOUTS, HOST, TEST_CURSOR_COOKIE_NAME, _logger, get_db_name
from .locks import release_test_lock
from .transaction import TransactionCase, flushing_cursor
from .browser import ChromeBrowser, ChromeBrowserException

class Opener(requests.Session):
    """
    Flushes and clears the current transaction when starting a request.

    This is likely necessary when we make a request to the server, as the
    request is made with a test cursor, which uses a different cache than this
    transaction.
    """
    def __init__(self, http_case: HttpCase):
        super().__init__()
        self.test_case = http_case
        self.cr = http_case.cr

    def request(self, *args, **kwargs):
        assert self.test_case.opener == self
        with flushing_cursor(self.cr), self.test_case.allow_requests():
            res = super().request(*args, **kwargs)
            res.__class__ = Response
            return res


class Response(requests.Response):
    @property
    def session(self) -> Session:
        """
        Get the session attached to the response.

        There are three cases:

        1. The session exists and was persisted on disk, you get the
           entire session and ``session.is_new`` is ``False``.
        2. The session exists but was not persisted on disk (because it
           only contained default values), you get an *empty* session
           but ``session.is_new`` is ``False``. This session is **not**
           populated with :func:`odoo.http.session.get_default_session`
           as the ``db`` and ``context['lang']`` cannot be set. Please
           adapt your test in this regard.
        3. The session doesn't exist, you get an empty session and
           ``session.is_new`` is ``True``.
        """
        session_id = (
            self.cookies.get('session_id')
            or self.request._cookies.get('session_id')
            or ''
        )
        return session_store().get(session_id, keep_sid=True)

    def raise_for_status(self) -> Response:
        try:
            super().raise_for_status()
        except requests.exceptions.HTTPError as exc:
            is_html = self.headers.get('content-type', '').startswith('text/html')
            is_website = is_html and b'<meta name="generator" content="Odoo"/>' in self.content
            if is_website:
                # The second container in <main> contains the error message
                main = self.text.partition('<main>')[2].partition('</main>')[0]
                c = '<div class="container">'
                error = main[main.find(c) + len(c):].partition(c)[2].partition('</div>')[0]
                exc.add_note(shorten(error, 150))
            elif is_html:
                exc.add_note(shorten(self.text.partition('</h1>')[2], 150))
            else:
                exc.add_note(shorten(self.text, 150))
            raise
        return self


class Transport(xmlrpclib.Transport):
    """ see :class:`Opener` """
    def __init__(self, http_case: HttpCase):
        self.test_case = http_case
        self.cr = http_case.cr
        super().__init__()

    def request(self, *args, **kwargs):
        with flushing_cursor(self.cr), self.test_case.allow_requests(all_requests=True):
            return super().request(*args, **kwargs)


class JsonRpcException(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class HttpCase(TransactionCase):
    """ Transactional HTTP TestCase with url_open and Chrome headless helpers. """
    browser = None
    browser_size = '1366x768'
    touch_enabled = False
    session: OdooHttpSession = None

    _logger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(cls.registry_test_mode())

        ICP = cls.env['ir.config_parameter']
        ICP.set_str('web.base.url', cls.base_url())
        ICP.env.flush_all()
        # v8 api with correct xmlrpc exception handling.
        cls.xmlrpc_url = f'{cls.base_url()}/xmlrpc/2/'
        cls._logger = logging.getLogger('%s.%s' % (cls.__module__, cls.__name__))

    @classmethod
    def base_url(cls):
        return f"http://{HOST}:{cls.http_port():d}"

    @classmethod
    def http_port(cls):
        return config['http_port']

    def setUp(self):
        super().setUp()

        self._logger = self._logger.getChild(self._testMethodName)

        self.xmlrpc_common = xmlrpclib.ServerProxy(self.xmlrpc_url + 'common', transport=Transport(self))
        self.xmlrpc_db = xmlrpclib.ServerProxy(self.xmlrpc_url + 'db', transport=Transport(self))
        self.xmlrpc_object = xmlrpclib.ServerProxy(self.xmlrpc_url + 'object', transport=Transport(self), use_datetime=True)
        # setup an url opener helper
        self.opener = Opener(self)
        self.http_key_sequence = itertools.count()
        # we need to allow requests during pdf rendering.
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
            self.startPatcher(
                patch.object(report_model, '_run_wkhtmltopdf', _patched_run_wkhtmltopdf),
            )

    @contextmanager
    def allow_pdf_render(self):
        _logger.warning("HTTPCase does not require calling allow_pdf_render")
        yield

    @contextmanager
    def allow_requests(self, browser: ChromeBrowser | None = None, all_requests=False):
        """
        Allows HTTP requests for the scope of the context.

        Params:
            browser (ChromeBrowser | None): if given, add the cookie to the browser.
            all_requests (bool): if True, allows all requests regardless of cookie.
        """
        with ExitStack() as defer:
            defer.enter_context(release_test_lock())
            if all_requests:
                self.http_request_allow_all = True
            new_key = f'{self.canonical_tag}__{next(self.http_key_sequence)}'
            defer.enter_context(patch.object(self, 'http_request_key', new_key))
            old_cookie = self.opener.cookies.get(TEST_CURSOR_COOKIE_NAME)
            if old_cookie:
                defer.callback(self.opener.cookies.set, TEST_CURSOR_COOKIE_NAME, old_cookie)
            else:
                defer.callback(self.opener.cookies.pop, TEST_CURSOR_COOKIE_NAME, None)
            self.opener.cookies[TEST_CURSOR_COOKIE_NAME] = new_key
            if browser:
                browser.set_cookie(
                    TEST_CURSOR_COOKIE_NAME, self.http_request_key, '/', HOST,
                )
            yield

    def parse_http_location(self, location):
        """ Parse a Location http header typically found in 201/3xx
        responses, return the corresponding parsed url object. The scheme/host
        are taken from ``base_url()`` in case they are missing from the
        header.
        """
        if not location:
            return urlsplit('')
        s = urlsplit(urljoin(self.base_url(), location))
        # normalise query parameters
        return s._replace(query=urlencode(parse_qsl(s.query)))

    def assertURLEqual(self, test_url, truth_url, message=None):
        """ Assert that two URLs are equivalent. If any URL is missing
        a scheme and/or host, assume the same scheme/host as base_url()
        """
        self.assertEqual(
            self.parse_http_location(test_url),
            self.parse_http_location(truth_url),
            message,
        )

    def build_rpc_payload(self, params=None):
        """
        Helper to properly build jsonrpc payload
        """
        return {
            "jsonrpc": "2.0",
            "method": "call",
            "id": str(uuid4()),
            "params": params or {},
        }

    def csrf_token(self):
        return Request.csrf_token(self)  # noqa: F821

    def url_open(self, url, data=None, files=None, timeout=12, headers=None, json=None, params=None, allow_redirects=True, cookies=None, method: str | None = None):
        if DISABLE_TIMEOUTS:
            timeout = None
        if not method and (data or files or json):
            method = 'POST'
        method = method or 'GET'
        if url.startswith('/'):
            url = self.base_url() + url
        return self.opener.request(method, url, params=params, data=data, json=json, files=files, timeout=timeout, headers=headers, cookies=cookies, allow_redirects=allow_redirects)

    def _wait_remaining_requests(self, timeout=10):

        def get_http_request_threads():
            return [
                t for t in threading.enumerate()
                if t.name.startswith('odoo.service.http.request')
                if getattr(t, 'processing_http', False)
            ]

        end_time = real_time() + timeout
        request_threads = get_http_request_threads()
        if not request_threads:
            return

        self._logger.info('waiting for threads: %s', request_threads)

        while real_time() < end_time:
            time.sleep(0.1)

        request_threads = get_http_request_threads()
        for thread in request_threads:
            self._logger.info("Stop waiting for thread %s handling request for url %s",
                                    thread.name, getattr(thread, 'url', '<UNKNOWN>'))

        if request_threads:
            self._logger.info('remaining requests')
            odoo.tools.misc.dumpstacks()

    def logout(self, keep_db=True):
        logout(self.session, keep_db=keep_db)
        session_store().save(self.session)

    def update_session(self, **items):
        self.session.update(**items)
        session_store().save(self.session)

    def update_session_context(self, **items):
        self.session['context'].update(**items)
        session_store().save(self.session)

    def authenticate(self, user, password, *, browser: ChromeBrowser = None, session_extra=()):
        if getattr(self, 'session', None):
            session_store().delete(self.session)

        self.session = session_store().new()
        self.session.update(
            get_default_session(),
            db=get_db_name(),
            _trace_disable=True,  # saves a query on all requests
        )
        self.session.context['lang'] = DEFAULT_LANG
        self.session.context['host_id'] = self.env['ir.http']._get_host_id_from_domain(self.base_url())

        if session_extra:
            if extra_ctx := session_extra.pop('context', None):
                self.session.context.update(extra_ctx)
            self.session.update(session_extra)

        if user: # if authenticated
            # Flush and clear the current transaction.  This is useful, because
            # the call below opens a test cursor, which uses a different cache
            # than this transaction.
            # In the context of a browser, the flush is already done.
            flushing = flushing_cursor(self.cr) if browser is None else contextlib.nullcontext()

            def patched_check_credentials(self, credential, env):
                return {'uid': self.id, 'auth_method': 'password', 'mfa': 'default'}

            # patching to speedup the check in case the password is hashed with many hashround + avoid to update the password
            with flushing, patch('odoo.addons.base.models.res_users.ResUsersPatchedInTest._check_credentials', new=patched_check_credentials):
                credential = {'login': user, 'password': password, 'type': 'password'}
                auth_info = self.env(context=self.session.context)['res.users'].authenticate(credential, {'interactive': False})
            uid = auth_info['uid']
            env = api.Environment(self.cr, uid, {})
            self.session['uid'] = uid
            self.session['login'] = user
            self.session['session_token'] = None
            if uid:
                update_session_token(self.session, env)
            self.session['context'] = dict(env['res.users'].context_get())
            if session_extra and (ctx := session_extra.get('context')):
                self.session['context'].update(ctx)

        session_store().save(self.session)
        # Reset the opener: turns out when we set cookies['foo'] we're really
        # setting a cookie on domain='' path='/'.
        #
        # But then our friendly neighborhood server might set a cookie for
        # domain='localhost' path='/' (with the same value) which is considered
        # a *different* cookie following ours rather than the same.
        #
        # When we update our cookie, it's done in-place, so the server-set
        # cookie is still present and (as it follows ours and is more precise)
        # very likely to still be used, therefore our session change is ignored.
        #
        # An alternative would be to set the cookie to None (unsetting it
        # completely) or clear-ing session.cookies.
        self.opener = Opener(self)
        self.opener.cookies.set("session_id", self.session.sid, domain=HOST)
        if browser:
            self._logger.info('Setting session cookie in browser')
            browser.set_cookie('session_id', self.session.sid, '/', HOST)

        return self.session

    def fetch_proxy(self, url):
        """
            This method is called every time a request is made from the chrome browser outside the local network
            Returns a response that will be sent to the browser to simulate the external request.
        """

        if 'https://fonts.googleapis.com/css' in url:
            _logger.info('External chrome request during tests: Return empty file for %s', url)
            return self.make_fetch_proxy_response('')  # return empty css file, we don't care

        _logger.info('External chrome request during tests: returning 404 for %s', url)
        return {
                'body': '',
                'responseCode': 404,
                'responseHeaders': [],
            }

    def make_fetch_proxy_response(self, content, code=200):
        if isinstance(content, str):
            content = content.encode()
        return {
                'body': base64.b64encode(content).decode(),
                'responseCode': code,
                'responseHeaders': [
                    {'name': 'access-control-allow-origin', 'value': '*'},
                    {'name': 'cache-control', 'value': 'public, max-age=10000'},
                ],
            }

    def browser_js(self, url_path, code, ready='', login=None, timeout=60, cookies=None, error_checker=None, watch=False, success_signal=DEFAULT_SUCCESS_SIGNAL, debug=False, cpu_throttling=None, **kw):
        """ Test JavaScript code running in the browser.

        To signal success test do: `console.log()` with the expected `success_signal`. Default is "test successful"
        To signal test failure raise an exception or call `console.error` with a message.
        Test will stop when a failure occurs if `error_checker` is not defined or returns `True` for this message

        :param string url_path: URL path to load the browser page on
        :param string code: JavaScript code to be executed
        :param string ready: JavaScript object to wait for before proceeding with the test
        :param string login: logged in user which will execute the test. e.g. 'admin', 'demo'
        :param int timeout: maximum time to wait for the test to complete (in seconds). Default is 60 seconds
        :param dict cookies: dictionary of cookies to set before loading the page
        :param error_checker: function to filter failures out.
            If provided, the function is called with the error log message, and if it returns `False` the log is ignored and the test continue
            If not provided, every error log triggers a failure
        :param bool watch: open a new browser window to watch the test execution
        :param string success_signal: string signal to wait for to consider the test successful
        :param bool debug: automatically open a fullscreen Chrome window with opened devtools and a debugger breakpoint set at the start of the tour.
            The tour is ran with the `debug=assets` query parameter. When an error is thrown, the debugger stops on the exception.
        :param int cpu_throttling: CPU throttling rate as a slowdown factor (1 is no throttle, 2 is 2x slowdown, etc)
        """
        if not self.env.registry.loaded:
            self._logger.warning('HttpCase test should be in post_install only')

        # increase timeout if coverage is running
        if any(f.filename.endswith('/coverage/execfile.py') for f in inspect.stack()  if f.filename):
            timeout = timeout * 1.5

        if debug is not False:
            watch = True
            timeout = 1e6
        elif DISABLE_TIMEOUTS:
            timeout = 1e6
        if watch:
            self._logger.warning('watch mode is only suitable for local testing')

        browser = ChromeBrowser(self, headless=not watch, success_signal=success_signal, debug=debug)
        with self.allow_requests(browser=browser), contextlib.ExitStack() as atexit:
            # Flush and clear the current transaction.  This is useful in case
            # we make requests to the server, as these requests are made with
            # test cursors, which uses different caches than this transaction.
            # Wait for all request before resetting the cursor.
            atexit.enter_context(flushing_cursor(self.cr))
            atexit.callback(self._wait_remaining_requests)
            atexit.enter_context(browser.cleanup)
            if "bus.bus" in self.env.registry:
                from odoo.addons.base.models.ir_http import IrHttp  # noqa: PLC0415
                from odoo.addons.bus.websocket import CloseCode, WebsocketConnectionHandler, _kick_all  # noqa: PLC0415

                atexit.callback(_kick_all, CloseCode.KILL_NOW)
                original_post_dispatch = IrHttp._post_dispatch

                def post_dispatch_wrapper(_, response):
                    original_post_dispatch(response)
                    # Trigger the creation of bus.bus records and notification dispatching
                    request.env.cr.precommit.run()
                    request.env.cr.postcommit.run()

                atexit.enter_context(patch.object(IrHttp, "_post_dispatch", classmethod(post_dispatch_wrapper)))
                atexit.enter_context(patch.object(
                    WebsocketConnectionHandler, "websocket_allowed", return_value=True
                ))

            self.authenticate(login, login, browser=browser)
            url = urljoin(self.base_url(), url_path)
            if watch:
                parsed = urlsplit(url)
                qs = dict(parse_qsl(parsed.query))
                qs['watch'] = '1'
                if debug is not False:
                    qs['debug'] = "assets"
                url = urlunsplit(parsed._replace(query=urlencode(qs)))
            self._logger.info('Open "%s" in browser', url)

            browser.screencaster.start()
            if cookies:
                for name, value in cookies.items():
                    browser.set_cookie(name, value, '/', HOST)

            cpu_throttling_os = os.environ.get('ODOO_BROWSER_CPU_THROTTLING')  # used by dedicated runbot builds
            cpu_throttling = int(cpu_throttling_os) if cpu_throttling_os else cpu_throttling

            if cpu_throttling:
                _logger.log(
                    logging.INFO if cpu_throttling_os else logging.WARNING,
                    'CPU throttling mode is only suitable for local testing - '
                    'Throttling browser CPU to %sx slowdown and extending timeout to %s sec', cpu_throttling, timeout)
                browser.throttle(cpu_throttling)

            browser.navigate_to(url, wait_stop=not bool(ready))

            # Needed because tests like test01.js (qunit tests) are passing a ready
            # code = ""
            self.assertTrue(browser._wait_ready(ready), 'The ready "%s" code was always falsy' % ready)

            error = None
            try:
                browser._wait_code_ok(code, timeout, error_checker=error_checker)
            except ChromeBrowserException as chrome_browser_exception:
                error = chrome_browser_exception
            if error:  # dont keep initial traceback, keep that outside of except
                self.fail(str(error))

    def start_tour(self, url_path, tour_name, step_delay=None, **kwargs):
        """Wrapper for `browser_js` to start the given `tour_name` with the
        optional delay between steps `step_delay`. Other arguments from
        `browser_js` can be passed as keyword arguments."""
        options = {
            'stepDelay': step_delay or 0,
            'debug': kwargs.get('debug', False),
        }
        code = kwargs.pop('code', f"odoo.startTour({tour_name!r}, {json.dumps(options)})")
        ready = kwargs.pop('ready', f"odoo.isTourReady({tour_name!r})")
        timeout = kwargs.pop('timeout', 60)

        if step_delay is not None:
            self._logger.warning('step_delay is only suitable for local testing')
        Users = self.registry['res.users']

        def _post_model_setup__(model):
            super(Users, model)._post_model_setup__()
            Users.tour_enabled = False

        with patch.object(Users, 'tour_enabled', False),\
                patch.object(Users, '_post_model_setup__', _post_model_setup__),\
                patch.object(Users, '_compute_tour_enabled', lambda _: None):
            self.browser_js(url_path=url_path, code=code, ready=ready, timeout=timeout, success_signal="tour succeeded", **kwargs)

    def profile(self, **kwargs):
        """
        for http_case, also patch _get_profiler_context_manager in order to profile all requests
        """
        sup = super()
        _profiler = sup.profile(**kwargs)
        def route_profiler(request):
            _route_profiler = sup.profile(description=request.httprequest.full_path, db=_profiler.db)
            _profiler.sub_profilers.append(_route_profiler)
            return _route_profiler
        return profiler.Nested(_profiler, patch('odoo.http.router._get_profiler_context_manager', route_profiler))

    def get_method_additional_tags(self, test_method):
        """
        guess if the test_methods is a tour and adds an `is_tour` tag on the test
        """
        additional_tags = super().get_method_additional_tags(test_method)
        if odoo.tools.config['test_tags'] and 'is_tour' in odoo.tools.config['test_tags']:
            method_source = inspect.getsource(test_method)
            if 'self.start_tour' in method_source:
                additional_tags.append('is_tour')
        return additional_tags

    def make_jsonrpc_request(self, route, params=None, headers=None, cookies=None, timeout=12):
        """Make a JSON-RPC request to the server.

        :raises requests.HTTPError: if one occurred
        :raises JsonRpcException: if the response contains an error
        """
        if DISABLE_TIMEOUTS:
            timeout = None
        response = self.opener.post(urljoin(self.base_url(), route), json={
            'id': 0,
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params or {},
        }, headers=headers, cookies=cookies, timeout=timeout)
        response.raise_for_status()
        decoded_response = response.json()
        if 'error' in decoded_response:
            raise JsonRpcException(
                code=decoded_response['error']['code'],
                message=decoded_response['error']['data']['name'],
            )
        return decoded_response['result']

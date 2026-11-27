# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Headless Chrome browser of the tests, and the recording of their screenshots."""

from __future__ import annotations

import binascii
import concurrent.futures
import itertools
import logging
import os
import signal
import tempfile
import threading
import time
import typing
import unittest
from concurrent.futures import CancelledError, Future, wait
from contextlib import ExitStack
import odoo.cli
from ..screencast import NoScreencast, Screencaster
from ..utils import DEFAULT_SUCCESS_SIGNAL, DISABLE_TIMEOUTS, _logger, get_db_name

if typing.TYPE_CHECKING:
    from ..http_case import HttpCase

from .exceptions import ChromeBrowserException
from .executable import _find_executable
from .files import save_test_file
from .transport import websocket
from . import events, process, transport


class ChromeBrowser:
    """ Helper object to control a Chrome headless process. """

    remote_debugging_port = 0  # 9222, change it in a non-git-tracked file

    def __init__(self, test_case: HttpCase, success_signal: str = DEFAULT_SUCCESS_SIGNAL, headless: bool = True, debug: bool = False):
        self.cleanup = ExitStack()
        self.throttling_factor = 1
        self._logger = test_case._logger
        self.test_case = test_case
        self.success_signal = success_signal
        if websocket is None:
            self._logger.warning("websocket-client module is not installed")
            raise unittest.SkipTest("websocket-client module is not installed")
        self.user_data_dir = self.cleanup.enter_context(
            tempfile.TemporaryDirectory(
                suffix='_chrome_odoo',
                ignore_cleanup_errors=True,
            )
        )
        self.cleanup.callback(
            self._logger.info,
            'Removing chrome user profile "%s"',
            self.user_data_dir,
        )
        self.chrome_log_level = logging.RUNBOT
        self.cleanup.callback(
            lambda: save_test_file(
                self.test_case._testMethodName,
                self.read_log(),
                prefix='chrome_log_',
                extension='txt',
                document_type="Chrome Log",
                logger=self._logger,
                loglevel=self.chrome_log_level,
                directory='chrome_logs',
            )
        )

        if os.name == 'posix':
            sigxcpu_handler = signal.signal(signal.SIGXCPU, self.signal_handler)
            self.cleanup.callback(
                signal.signal, signal.SIGXCPU, sigxcpu_handler)

        test_case.browser_size = test_case.browser_size.replace('x', ',')

        self.chrome, self.devtools_port = self.cleanup.enter_context(self._chrome_start(
            user_data_dir=self.user_data_dir,
            touch_enabled=test_case.touch_enabled,
            headless=headless,
            debug=debug,
        ))
        self.ws = self.cleanup.enter_context(self._open_websocket())
        if scs := odoo.tools.config['screencasts']:
            self.screencaster = self.cleanup.enter_context(Screencaster(self, scs))
        else:
            self.screencaster = self.cleanup.enter_context(NoScreencast())

        self._request_id = itertools.count()
        self._result = Future()
        self.error_checker = None
        self.had_failure = False
        # maps request_id to Futures
        self._responses = {}
        # maps frame ids to callbacks
        self._frames = {}
        self._handlers = {
            'Fetch.requestPaused': self._handle_request_paused,
            'Runtime.consoleAPICalled': self._handle_console,
            'Runtime.exceptionThrown': self._handle_exception,
            'Page.frameStoppedLoading': self._handle_frame_stopped_loading,
            'Page.screencastFrame': self.screencaster,
        }
        self._receiver = threading.Thread(
            target=self._receive,
            name="WebSocket events consumer",
            args=(get_db_name(),)
        )
        self._receiver.start()
        self._logger.info('Enable chrome headless console log notification')
        self._websocket_send('Runtime.enable')
        self._websocket_request('Fetch.enable')
        self._logger.info('Chrome headless enable page notifications')
        self._websocket_send('Page.enable')
        self._websocket_send('Page.setDownloadBehavior', params={
            'behavior': 'deny',
            'eventsEnabled': False,
        })
        self._websocket_send('Emulation.setFocusEmulationEnabled', params={'enabled': True})
        emulated_device = {
            'mobile': False,
            'width': None,
            'height': None,
            'deviceScaleFactor': 1,
        }
        emulated_device['width'], emulated_device['height'] = [int(size) for size in test_case.browser_size.split(",")]
        self._websocket_request('Emulation.setDeviceMetricsOverride', params=emulated_device)
        self.cleanup.callback(self._ws_winddown)

    def _ws_winddown(self):
        try:
            self._websocket_request('Page.stopLoading')
            self._websocket_request('Runtime.evaluate', params={'expression': """
            ('serviceWorker' in navigator) &&
                navigator.serviceWorker.getRegistrations().then(
                    registrations => Promise.all(registrations.map(r => r.unregister()))
                )
            """, 'awaitPromise': True})
            # wait for the screenshot or whatever
            wait(self._responses.values(), 10)
            self._result.cancel()

            self._logger.info("Closing chrome headless with pid %s", self.chrome.pid)
            self._websocket_request('Browser.close')
        except ChromeBrowserException as e:
            _logger.runbot("WS error during browser shutdown: %s", e)
            self.chrome_log_level = logging.RUNBOT
        except Exception:  # noqa: BLE001
            _logger.warning("Error during browser shutdown", exc_info=True)
            self.chrome_log_level = logging.RUNBOT

    def signal_handler(self, sig, frame):
        if sig == signal.SIGXCPU:
            _logger.info('CPU time limit reached, stopping Chrome and shutting down')
            self.stop()
            exit()

    def throttle(self, factor: int | None) -> None:
        if not factor:
            return

        assert 1 <= factor <= 50  # arbitrary upper limit
        self.throttling_factor = factor
        self._websocket_request('Emulation.setCPUThrottlingRate', params={'rate': factor})

    def stop(self):
        self.cleanup.close()

    @property
    def executable(self):
        try:
            return _find_executable()
        except Exception:
            self._logger.warning('Chrome executable not found')
            raise

    def _spawn_chrome(self, cmd):
        return process._spawn_chrome(self, cmd)

    def _chrome_start(self, user_data_dir: str, touch_enabled: bool, headless=True, debug=False):
        return process._chrome_start(self, user_data_dir, touch_enabled, headless, debug)

    def read_log(self) -> bytes:
        return process.read_log(self)

    def _json_command(self, command, timeout=3):
        return transport._json_command(self, command, timeout)

    def _open_websocket(self):
        return transport._open_websocket(self)

    def _receive(self, dbname):
        return transport._receive(self, dbname)

    def _websocket_request(self, method, *, params=None, timeout=10.0):
        return transport._websocket_request(self, method, params=params, timeout=timeout)

    def _websocket_send(self, method, *, params=None, with_future=False):
        return transport._websocket_send(self, method, params=params, with_future=with_future)

    def _handle_request_paused(self, **params):
        return events._handle_request_paused(self, **params)

    def _handle_console(self, type, args=None, stackTrace=None, **kw):
        return events._handle_console(self, type, args, stackTrace, **kw)

    def _handle_exception(self, exceptionDetails, timestamp):
        return events._handle_exception(self, exceptionDetails, timestamp)

    def _handle_frame_stopped_loading(self, frameId):
        return events._handle_frame_stopped_loading(self, frameId)

    _TO_LEVEL = {
        'debug': logging.DEBUG,
        'log': logging.INFO,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'dir': logging.RUNBOT,
        # TODO: what do with
        # dir, dirxml, table, trace, clear, startGroup, startGroupCollapsed,
        # endGroup, assert, profile, profileEnd, count, timeEnd
    }

    def take_screenshot(self, prefix='sc_') -> Future[dict]:
        def handler(f):
            try:
                base_png = f.result(timeout=0)['data']
            except Exception as e:
                self._logger.runbot("Couldn't capture screenshot: %s", e)
                return
            if not base_png:
                self._logger.runbot("Couldn't capture screenshot: expected image data, got %r", base_png)
                return
            decoded = binascii.a2b_base64(base_png)
            save_test_file(self.test_case._testMethodName, decoded, prefix, logger=self._logger, directory='screenshots')

        self._logger.info('Asking for screenshot')
        f = self._websocket_send('Page.captureScreenshot', with_future=True)
        if f:
            f.add_done_callback(handler)
        return f

    def set_cookie(self, name, value, path, domain):
        params = {'name': name, 'value': value, 'path': path, 'domain': domain}
        self._websocket_request('Network.setCookie', params=params)

    def delete_cookie(self, name, **kwargs):
        params = {k: v for k, v in kwargs.items() if k in ['url', 'domain', 'path']}
        params['name'] = name
        self._websocket_request('Network.deleteCookies', params=params)

    def _wait_ready(self, ready_code=None, timeout=60):
        if timeout:
            timeout *= self.throttling_factor
        ready_code = ready_code or "document.readyState === 'complete'"
        self._logger.info('Evaluate ready code "%s"', ready_code)
        start_time = time.time()
        result = None
        while True:
            taken = time.time() - start_time
            if taken > timeout:
                break

            try:
                result = self._websocket_request('Runtime.evaluate', params={
                    'expression': "try { %s } catch {}" % ready_code,
                    'awaitPromise': True,
                }, timeout=timeout-taken)['result']
            except CancelledError:
                exc = self._result.done() and self._result.exception()
                if exc:
                    raise exc from None
                result = "cancelled"

            if result == {'type': 'boolean', 'value': True}:
                time_to_ready = time.time() - start_time
                if taken > 2:
                    self._logger.info('The ready code tooks too much time : %s', time_to_ready)
                return True

        exc = self._result.done() and self._result.exception()
        if exc:
            raise exc from None
        self.take_screenshot(prefix='sc_failed_ready_')
        self._logger.info('Ready code last try result: %s', result)
        return False

    def _wait_code_ok(self, code, timeout, error_checker=None):
        if timeout:
            timeout *= self.throttling_factor
        self.error_checker = error_checker
        self._logger.info('Evaluate test code "%s"', code)
        start = time.time()
        res = self._websocket_request('Runtime.evaluate', params={
            'expression': code,
            'awaitPromise': True,
        }, timeout=timeout)['result']
        if res.get('subtype') == 'error':
            raise ChromeBrowserException("Running code returned an error: %s" % res)

        err = ChromeBrowserException("failed")
        try:
            # if the runcode was a promise which took some time to execute,
            # discount that from the timeout
            if self._result.result(time.time() - start + timeout) and not self.had_failure:
                self.chrome_log_level = logging.INFO
                return
        except CancelledError:
            # regular-ish shutdown
            self.chrome_log_level = logging.INFO
            return
        except ChromeBrowserException:
            self.screencaster.save()
            raise
        except Exception as e:
            err = e

        self.take_screenshot()
        self.screencaster.save()

        if isinstance(err, concurrent.futures.TimeoutError):
            raise ChromeBrowserException('Script timeout exceeded') from err
        raise ChromeBrowserException("Unknown error") from err

    def navigate_to(self, url, wait_stop=False):
        self._logger.info('Navigating to: "%s"', url)
        timeout = 1e6 if DISABLE_TIMEOUTS else 20.0
        nav_result = self._websocket_request('Page.navigate', params={'url': url}, timeout=timeout)
        self._logger.info("Navigation result: %s", nav_result)
        if wait_stop:
            frame_id = nav_result['frameId']
            e = threading.Event()
            self._frames[frame_id] = e.set
            self._logger.info('Waiting for frame %r to stop loading', frame_id)
            e.wait(10)

    def _from_remoteobject(self, arg):
        return events._from_remoteobject(self, arg)

    LINE_PATTERN = '\tat %(functionName)s (%(url)s:%(lineNumber)d:%(columnNumber)d)\n'

    def _format_stack(self, logrecord):
        return events._format_stack(self, logrecord)

    def console_formatter(self, args):
        return events.console_formatter(self, args)

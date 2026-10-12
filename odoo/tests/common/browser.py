# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Headless Chrome browser of the tests, and the recording of their screenshots."""

from __future__ import annotations

import binascii
import concurrent.futures
import contextlib
import itertools
import json
import logging
import os
import pathlib
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import typing
import unittest
from concurrent.futures import CancelledError, Future, InvalidStateError, wait
from contextlib import ExitStack
from datetime import datetime
from functools import cache
from itertools import islice, zip_longest
from textwrap import shorten
import psutil
import requests
import odoo.cli
import odoo.models
import odoo.orm.models.registry
from odoo.tools.misc import find_in_path
import odoo.addons.base

if typing.TYPE_CHECKING:
    from .http_case import HttpCase

try:
    import websocket
except ImportError:
    # chrome headless tests will be skipped
    websocket = None

from .utils import BROWSER_WAIT, CHECK_BROWSER_ITERATIONS, CHECK_BROWSER_SLEEP, DEFAULT_SUCCESS_SIGNAL, DISABLE_TIMEOUTS, HOST, IGNORED_MSGS, _logger, get_db_name, run

class ChromeBrowserException(Exception):
    pass


def save_test_file(test_name, content, prefix, extension='png', logger=_logger, document_type='Screenshot', date_format="%Y%m%d_%H%M%S_%f", loglevel=logging.RUNBOT, directory=''):
    assert re.fullmatch(r'\w*_', prefix)
    assert re.fullmatch(r'[a-z]+', extension)
    assert re.fullmatch(r'\w+', test_name)
    now = datetime.now().strftime(date_format)
    dest = pathlib.Path(odoo.tools.config['screenshots']) / get_db_name() / directory
    dest.mkdir(parents=True, exist_ok=True)
    full_path = dest / f'{prefix}{now}_{test_name}.{extension}'
    full_path.write_bytes(content)
    logger.log(loglevel, "%s in: %s", document_type, full_path)


if os.name == 'posix' and platform.system() != 'Darwin':
    # since the introduction of pointer compression in Chrome 80 (v8 v8.0),
    # the memory reservation algorithm requires more than 8GiB of
    # virtual mem for alignment this exceeds our default memory limits.
    def _preexec():
        import resource  # noqa: PLC0415
        resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
else:
    _preexec = None


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
        # pylint: disable=subprocess-popen-preexec-fn
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.DEVNULL,
            preexec_fn=_preexec,
            env={**os.environ, 'TMPDIR': self.user_data_dir},
        )  # noqa: PLW1509

        port_file = pathlib.Path(self.user_data_dir, 'DevToolsActivePort')
        for _ in range(CHECK_BROWSER_ITERATIONS):
            time.sleep(CHECK_BROWSER_SLEEP)
            if port_file.is_file() and port_file.stat().st_size >= 5:
                with port_file.open('r', encoding='utf-8') as f:
                    return proc, int(f.readline())

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        self._logger.warning(
            'Chrome headless failed to start:\n%s',
            self.read_log().decode(),
        )
        if port_file.is_file():
            content = port_file.read_text('utf-8')
            _logger.warning('DevToolsActivePort content: %r', content)
        else:
            _logger.warning('DevToolsActivePort not found')
        self.stop()

        raise unittest.SkipTest(f'Failed to detect chrome devtools port after {BROWSER_WAIT :.1f}s.')

    @contextlib.contextmanager
    def _chrome_start(
            self,
            user_data_dir: str,
            touch_enabled: bool,
            headless=True,
            debug=False,
    ):
        headless_switches = {
            '--headless': '',
            '--disable-extensions': '',  # Disable all chrome extensions
            '--disable-component-extensions-with-background-pages': '',  # Disable built-in extensions (e.g., PDF viewer, Hangouts...)
            '--disable-background-networking': '',  # Stop background requests (telemetry, updates, safe browsing)
            '--disable-background-timer-throttling': '',  # Prevent Chrome from slowing down JS in inactive tabs
            '--disable-backgrounding-occluded-windows': '',  # Prevent Chrome from suspending hidden windows
            '--disable-renderer-backgrounding': '',  # Keep background rendering processes running at normal priority
            '--disable-breakpad': '',  # Disable the Breakpad crash reporting system
            '--disable-client-side-phishing-detection': '',  # Disable local machine-learning phishing analysis
            '--disable-crash-reporter': '',  # Disable crash report generation
            '--disable-dev-shm-usage': '',  # Use /tmp instead of /dev/shm
            '--disable-namespace-sandbox': '',  # Disable Linux namespace sandboxing
            '--disable-sync': '',  # Completely disable Google account synchronization engine
            '--no-crash-upload': '',  # Prevent uploading crash dumps to Google servers
            '--no-sandbox': '',  # Disable OS-level sandboxing
            '--disable-gpu': '',  # Disable hardware GPU acceleration
            '--enable-unsafe-swiftshader': '',  # Allow software rendering fallback for WebGL when GPU is disabled
            '--mute-audio': '',  # Prevent audio playback from allocating system resources
            '--font-render-hinting': 'none',  # Disable sub-pixel font rendering calculations
            '--disable-gpu-early-init': '',  # Disable proactive early init of GPU process
            '--disable-gpu-sandbox': '',  # Disables the GPU process sandbox
            '--disable-gpu-driver-bug-workarounds': '',  # Disable workarounds for various GPU driver bugs
        }
        switches = {
            # required for tours that use Youtube autoplay conditions (namely website_slides' "course_tour")
            '--autoplay-policy': 'no-user-gesture-required',  # Allow media autoplay without requiring a user click
            '--disable-default-apps': '',  # Disable installation of default apps
            '--disable-domain-reliability': '',  # Stop tracking and sending telemetry for failed network requests
            '--disable-search-engine-choice-screen': '',  # Bypass the EU search engine selection prompt on startup
            '--disable-features': ','.join([
                'Translate',  # Disables Chrome translation
                'MediaRouter',  # Stop scanning for local Cast or media devices
                'InterestFeedContentSuggestions',  # Disables the Discover feed on NTP
            ]),
            '--ash-no-nudges': '',  # Avoids blue bubble "user education" nudges (eg., "… give your browser a new look", Memory Saver)
            '--propagate-iph-for-testing': '',  # Disable all in-product help (IPH) features
            '--no-default-browser-check': '',  # Bypass the prompt asking to make Chrome the default browser
            '--no-first-run': '',  # Skip the welcome screen and first-run setup wizards
            '--proxy-server': '"direct://"',  # Force a direct connection, bypassing any system proxies
            '--proxy-bypass-list': '*',  # Bypass proxy for all domains (eliminates local resolution delays)
            '--remote-debugging-address': HOST,
            '--remote-debugging-port': str(self.remote_debugging_port),
            '--user-data-dir': user_data_dir,
            '--enable-logging': '',
            '--v': str(int(os.environ.get("ODOO_BROWSER_LOG_VERBOSITY", "0"))),
            # FIXME: these next 2 flags are temporarily uncommented to allow client
            # code to manually run garbage collection. This is done as currently
            # the Chrome unit test process doesn't have access to its available
            # memory, so it cannot run the GC efficiently and may run out of memory
            # and crash. These should be re-commented when the process is correctly
            # configured.
            '--enable-precise-memory-info': '',
            '--js-flags': '--expose-gc',
        }
        if headless:
            switches.update(headless_switches)
        if touch_enabled:
            # enable Chrome's Touch mode, useful to detect touch capabilities using
            # "'ontouchstart' in window"
            switches['--touch-events'] = ''
        if debug is not False:
            switches['--auto-open-devtools-for-tabs'] = ''
            switches['--start-fullscreen'] = ''

        cmd = [self.executable]
        cmd += ['%s=%s' % (k, v) if v else k for k, v in switches.items()]
        url = 'about:blank'
        cmd.append(url)
        try:
            proc, devtools_port = self._spawn_chrome(cmd)
        except OSError:
            raise unittest.SkipTest("%s not found" % cmd[0])
        self._logger.info('Chrome pid: %s', proc.pid)
        self._logger.info('Chrome headless temporary user profile dir: %s', self.user_data_dir)
        try:
            yield proc, devtools_port
        finally:
            self._logger.info("Terminating chrome headless with pid %s", proc.pid)
            main = psutil.Process(proc.pid)
            procs = [main] + main.children(recursive=True)
            proc.terminate()
            _, alive = psutil.wait_procs(procs, 5)
            if alive:  # can't early exit, it suppresses the finally'd exception if any
                self._logger.warning(
                    "Killing chrome descendants-or-self of %s: %d remaining%s",
                    proc.pid,
                    len(alive),
                    "".join(f"\n- {p.name()} ({p.status()})" for p in alive),
                )
                for p in alive:
                    p.kill()
                psutil.wait_procs(alive, 1)
                self.chrome_log_level = logging.RUNBOT

    def read_log(self) -> bytes:
        try:
            return pathlib.Path(self.user_data_dir, 'chrome_debug.log').read_bytes()
        except FileNotFoundError:
            return b''

    def _json_command(self, command, timeout=3):
        """Queries browser state using JSON

        Available commands:

        ``''``
            return list of tabs with their id
        ``list`` (or ``json/``)
            list tabs
        ``new``
            open a new tab
        :samp:`activate/{id}`
            activate a tab
        :samp:`close/{id}`
            close a tab
        ``version``
            get chrome and dev tools version
        ``protocol``
            get the full protocol
        """
        url = f'http://{HOST}:{self.devtools_port}/json/{command}'.rstrip('/')
        self._logger.info("Issuing json command %s", url)
        delay = 0.1
        tries = 0
        failure_info = None
        message = None
        while timeout > 0:
            if self.chrome.poll() is not None:
                message = 'Chrome crashed at startup'
                break
            try:
                r = requests.get(url, timeout=3)
                if r.ok:
                    return r.json()
            except requests.ConnectionError as e:
                failure_info = str(e)
                message = 'Connection Error while trying to connect to Chrome debugger'
            except requests.exceptions.ReadTimeout as e:
                failure_info = str(e)
                message = 'Connection Timeout while trying to connect to Chrome debugger'
                break

            time.sleep(delay)
            timeout -= delay
            delay = delay * 1.5
            tries += 1
        self._logger.error("%s after %s tries" % (message, tries))
        if failure_info:
            self._logger.info(failure_info)
        self.stop()
        raise unittest.SkipTest("Error during Chrome headless connection")

    @contextlib.contextmanager
    def _open_websocket(self):
        version = self._json_command('version')
        self._logger.info('Browser version: %s', version['Browser'])

        start = time.time()
        while (time.time() - start) < 5.0:
            ws_url = next((
                target['webSocketDebuggerUrl']
                for target in self._json_command('')
                if target['type'] == 'page'
                if target['url'] == 'about:blank'
            ), None)
            if ws_url:
                break

            time.sleep(0.1)
        else:
            self.stop()
            raise unittest.SkipTest("Error during Chrome connection: never found 'page' target")

        self._logger.info('Websocket url found: %s', ws_url)
        ws = websocket.create_connection(ws_url, enable_multithread=True, suppress_origin=True)
        if ws.getstatus() != 101:
            raise unittest.SkipTest("Cannot connect to chrome dev tools")
        ws.settimeout(0.01)
        try:
            yield ws
        finally:
            self._logger.info("Closing websocket connection")
            ws.close()

    def _receive(self, dbname):
        threading.current_thread().dbname = dbname
        # So CDT uses a streamed JSON-RPC structure, meaning a request is
        # {id, method, params} and eventually a {id, result | error} should
        # arrive the other way, however for events it uses "notifications"
        # meaning request objects without an ``id``, but *coming from the server
        while True: # or maybe until `self._result` is `done()`?
            try:
                msg = self.ws.recv()
                if not msg:
                    continue
                self._logger.debug('\n<- %s', msg)
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException as e:
                if not self._result.done():
                    del self.ws
                    self._result.set_exception(e)
                    while True:
                        try:
                            _, f = self._responses.popitem()
                        except KeyError:
                            break
                        else:
                            f.cancel()
                return
            except Exception as e:
                if isinstance(e, ConnectionResetError) and self._result.done():
                    return
                # if the socket is still connected something bad happened,
                # otherwise the client was just shut down
                if self.ws.connected:
                    self._result.set_exception(e)
                    raise
                self._result.cancel()
                return

            res = json.loads(msg)
            request_id = res.get('id')
            try:
                if request_id is None:
                    if handler := self._handlers.get(res['method']):
                        handler(**res['params'])
                elif f := self._responses.pop(request_id, None):
                    if 'result' in res:
                        f.set_result(res['result'])
                    else:
                        f.set_exception(ChromeBrowserException(res['error']['message']))
            except Exception:
                _logger.exception(
                    "While processing message %s",
                    shorten(str(msg), 500, placeholder='...'),
                )

    def _websocket_request(self, method, *, params=None, timeout=10.0):
        assert threading.get_ident() != self._receiver.ident,\
            "_websocket_request must not be called from the consumer thread"
        if not hasattr(self, 'ws'):
            return None
        if DISABLE_TIMEOUTS:
            timeout = None
        else:
            timeout *= self.throttling_factor

        f = self._websocket_send(method, params=params, with_future=True)
        try:
            return f.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f'{method}({params or ""})')

    def _websocket_send(self, method, *, params=None, with_future=False):
        """send chrome devtools protocol commands through websocket

        If ``with_future`` is set, returns a ``Future`` for the operation.
        """
        if not hasattr(self, 'ws'):
            return None

        result = None
        request_id = next(self._request_id)
        if with_future:
            result = self._responses[request_id] = Future()
        payload = {'method': method, 'id': request_id}
        if params:
            payload['params'] = params
        self._logger.debug('\n-> %s', payload)
        self.ws.send(json.dumps(payload))
        return result

    def _handle_request_paused(self, **params):
        url = params['request']['url']
        if url.startswith(f'http://{HOST}'):
            cmd = 'Fetch.continueRequest'
            response = {}
        else:
            cmd = 'Fetch.fulfillRequest'
            response = self.test_case.fetch_proxy(url)
        try:
            self._websocket_send(cmd, params={'requestId': params['requestId'], **response})
        except websocket.WebSocketConnectionClosedException:
            pass
        except (BrokenPipeError, ConnectionResetError, OSError):
            # this can happen if the browser is closed. Just ignore it.
            _logger.info("Websocket error while handling request %s", params['request']['url'])

    def _handle_console(self, type, args=None, stackTrace=None, **kw): # pylint: disable=redefined-builtin
        # console formatting differs somewhat from Python's, if args[0] has
        # format modifiers that many of args[1:] get formatted in, missing
        # args are replaced by empty strings and extra args are concatenated
        # (space-separated)
        #
        # current version modifies the args in place which could and should
        # probably be improved
        if args:
            arg0, args = str(self._from_remoteobject(args[0])), args[1:]
        else:
            arg0, args = '', []
        formatted = [re.sub(r'%[%sdfoOc]', self.console_formatter(args), arg0)]
        # formatter consumes args it uses, leaves unformatted args untouched
        formatted.extend(str(self._from_remoteobject(arg)) for arg in args)
        message = ' '.join(formatted)
        stack = ''.join(self._format_stack({'type': type, 'stackTrace': stackTrace}))
        if stack:
            message += '\n' + stack

        log_type = type
        _logger = self._logger.getChild('browser')
        if self._result.done() and IGNORED_MSGS(message):
            log_type = 'dir'
        _logger.log(
            self._TO_LEVEL.get(log_type, logging.INFO),
            "%s%s",
            "Error received after termination: " if self._result.done() else "",
            message # might still have %<x> characters
        )

        if log_type == 'error':
            self.had_failure = True
            if self._result.done():
                return
            if not self.error_checker or self.error_checker(message):
                self.take_screenshot()
                try:
                    self._result.set_exception(ChromeBrowserException(message))
                except CancelledError:
                    ...
                except InvalidStateError:
                    self._logger.warning(
                        "Trying to set result to failed (%s) but found the future settled (%s)",
                        message, self._result
                    )
        elif message == self.success_signal:
            @run
            def _get_heap():
                yield self._websocket_send("HeapProfiler.collectGarbage", with_future=True)
                r = yield self._websocket_send("Runtime.getHeapUsage", with_future=True)
                _logger.info("heap %d (allocated %d)", r['usedSize'], r['totalSize'])

            @run
            def _check_form():
                node_id = 0

                with contextlib.suppress(Exception):
                    d = yield self._websocket_send('DOM.getDocument', params={'depth': 0}, with_future=True)
                    form = yield self._websocket_send("DOM.querySelector", params={
                        'nodeId': d['root']['nodeId'],
                        'selector': '.o_form_dirty',
                    }, with_future=True)
                    node_id = form['nodeId']

                if node_id:
                    self.take_screenshot("unsaved_form_")
                    msg = """\
Tour finished with a dirty form view being open.

Dirty form views are automatically saved when the page is closed, \
which leads to stray network requests and inconsistencies."""
                    if self._result.done():
                        _logger.error("%s", msg)
                    else:
                        self._result.set_exception(ChromeBrowserException(msg))
                    return

                if not self._result.done():
                    self._result.set_result(True)
                elif self._result.exception() is None:
                    _logger.error("Tried to make the tour successful twice.")


    def _handle_exception(self, exceptionDetails, timestamp):
        message = exceptionDetails['text']
        exception = exceptionDetails.get('exception')
        if exception:
            message += str(self._from_remoteobject(exception))
        exceptionDetails['type'] = 'trace'  # fake this so _format_stack works
        stack = ''.join(self._format_stack(exceptionDetails))
        if stack:
            message += '\n' + stack

        if self._result.done():
            if not IGNORED_MSGS(message):
                self._logger.getChild('browser').error(
                    "Exception received after termination: %s", message)
            return

        self.take_screenshot()
        try:
            self._result.set_exception(ChromeBrowserException(message))
        except CancelledError:
            ...
        except InvalidStateError:
            self._logger.warning(
                "Trying to set result to failed (%s) but found the future settled (%s)",
                message, self._result
            )

    def _handle_frame_stopped_loading(self, frameId):
        wait = self._frames.pop(frameId, None)
        if wait:
            wait()

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
        """ attempts to make a CDT RemoteObject comprehensible
        """
        objtype = arg['type']
        subtype = arg.get('subtype')
        if objtype == 'undefined':
            # the undefined remoteobject is literally just {type: undefined}...
            return 'undefined'
        elif objtype != 'object' or subtype not in (None, 'array'):
            # value is the json representation for json object
            # otherwise fallback on the description which is "a string
            # representation of the object" e.g. the traceback for errors, the
            # source for functions, ... finally fallback on the entire arg mess
            return arg.get('value', arg.get('description', arg))
        elif subtype == 'array':
            # apparently value is *not* the JSON representation for arrays
            # instead it's just Array(3) which is useless, however the preview
            # properties are the same as object which is useful (just ignore the
            # name which is the index)
            return '[%s]' % ', '.join(
                repr(p['value']) if p['type'] == 'string' else str(p['value'])
                for p in arg.get('preview', {}).get('properties', [])
                if re.match(r'\d+', p['name'])
            )
        # all that's left is type=object, subtype=None aka custom or
        # non-standard objects, print as TypeName(param=val, ...), sadly because
        # of the way Odoo widgets are created they all appear as Class(...)
        # nb: preview properties are *not* recursive, the value is *all* we get
        return '%s(%s)' % (
            arg.get('className') or 'object',
            ', '.join(
                '%s=%s' % (p['name'], repr(p['value']) if p['type'] == 'string' else p['value'])
                for p in arg.get('preview', {}).get('properties', [])
                if p.get('value') is not None
            )
        )

    LINE_PATTERN = '\tat %(functionName)s (%(url)s:%(lineNumber)d:%(columnNumber)d)\n'
    def _format_stack(self, logrecord):
        if logrecord['type'] not in ['trace']:
            return

        trace = logrecord.get('stackTrace')
        while trace:
            for f in trace['callFrames']:
                yield self.LINE_PATTERN % f
            trace = trace.get('parent')

    def console_formatter(self, args):
        """ Formats similarly to the console API:

        * if there are no args, don't format (return string as-is)
        * %% -> %
        * %c -> replace by styling directives (ignore for us)
        * other known formatters -> replace by corresponding argument
        * leftover known formatters (args exhausted) -> replace by empty string
        * unknown formatters -> return as-is
        """
        if not args:
            return lambda m: m[0]

        def replacer(m):
            fmt = m[0][1]
            if fmt == '%':
                return '%'
            if fmt in 'sdfoOc':
                if not args:
                    return ''
                repl = args.pop(0)
                if fmt == 'c':
                    return ''
                return str(self._from_remoteobject(repl))
            return m[0]
        return replacer


class NoScreencast:
    def start(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def save(self):
        pass

    def __call__(self, sessionId, data, metadata):
        pass


class Screencaster:
    def __init__(self, browser: ChromeBrowser, directory: str):
        self.stopped = False
        self.browser: ChromeBrowser = browser
        self._logger: logging.Logger = browser._logger
        self.directory = pathlib.Path(directory, get_db_name(), 'screencasts')
        ts = datetime.now()
        self.frames_dir = self.directory / f'frames-{ts:%Y%m%dT%H%M%S.%f}'
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.frames = []

    def start(self):
        self._logger.info('Starting screencast')
        self.browser._websocket_send('Page.startScreencast')

    def __call__(self, sessionId, data, metadata):
        self.browser._websocket_send('Page.screencastFrameAck', params={'sessionId': sessionId})
        if self.stopped:
            # if already stopped, drop the frames as we might have removed the directory already
            return
        outfile = self.frames_dir / f'frame_{len(self.frames):05d}.png'
        try:
            outfile.write_bytes(binascii.a2b_base64(data.encode()))
        except FileNotFoundError:
            return
        self.frames.append({
            'file_path': outfile,
            'timestamp': metadata.get('timestamp')
        })

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.browser._websocket_send('Page.stopScreencast')
        self.stopped = True
        if self.frames_dir.is_dir():
            shutil.rmtree(self.frames_dir, ignore_errors=True)

    def save(self):
        if self.stopped:
            return
        self.browser._websocket_send('Page.stopScreencast')
        # Wait for frames just in case, ideally we'd wait for the Browse.close
        # event or something but that doesn't exist.
        time.sleep(5)
        self.stopped = True
        if not self.frames:
            self._logger.debug('No screencast frames to encode')
            return

        frames, self.frames = self.frames, []
        t = time.time()
        duration = 1/24
        concat_script_path = self.frames_dir.with_suffix('.txt')
        with concat_script_path.open("w") as concat_file:
            for f, next_frame in zip_longest(frames, islice(frames, 1, None)):
                frame_file_path = f['file_path']

                if f['timestamp'] is not None:
                    end_time = next_frame['timestamp'] if next_frame else t
                    duration = end_time - f['timestamp']
                concat_file.write(f"file '{frame_file_path}'\nduration {duration}\n")
            concat_file.write(f"file '{frame_file_path}'")  # needed by the concat plugin

        try:
            ffmpeg_path = find_in_path('ffmpeg')
        except IOError:
            self._logger.runbot('Screencast frames in: %s', self.frames_dir)
            return

        outfile = self.frames_dir.with_suffix('.mp4')
        try:
            subprocess.run([
                ffmpeg_path,
                '-y', '-loglevel', 'warning',
                '-f', 'concat', '-safe', '0', '-i', concat_script_path,
                '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                '-c:v', 'libx265', '-x265-params', 'lossless=1',
                outfile,
            ], preexec_fn=_preexec, check=True)
        except subprocess.CalledProcessError:
            self._logger.error('Failed to encode screencast, screencast frames in %s', self.frames_dir)
        else:
            concat_script_path.unlink()
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            self._logger.runbot('Screencast in: %s', outfile)


@cache
def _find_executable():
    browser_bin_path = os.environ.get('ODOO_BROWSER_BIN')  # used for testing specific Chrome builds
    if browser_bin_path and os.path.exists(browser_bin_path):
        return browser_bin_path
    system = platform.system()
    if system == 'Linux':
        for bin_ in ['google-chrome', 'chromium', 'chromium-browser', 'google-chrome-stable']:
            try:
                return find_in_path(bin_)
            except IOError:
                continue

    elif system == 'Darwin':
        bins = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]
        for bin_ in bins:
            if os.path.exists(bin_):
                return bin_

    elif system == 'Windows':
        bins = [
            '%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe',
            '%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe',
            '%LocalAppData%\\Google\\Chrome\\Application\\chrome.exe',
        ]
        for bin_ in bins:
            bin_ = os.path.expandvars(bin_)
            if os.path.exists(bin_):
                return bin_

    raise unittest.SkipTest("Chrome executable not found")

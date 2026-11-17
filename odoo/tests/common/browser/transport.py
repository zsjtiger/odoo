# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Communication with Chrome through the devtools protocol: the HTTP endpoints and the websocket."""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import threading
import time
import typing
import unittest
from concurrent.futures import Future
from textwrap import shorten
import requests
from ..utils import DISABLE_TIMEOUTS, HOST, _logger

if typing.TYPE_CHECKING:
    pass

from .exceptions import ChromeBrowserException

try:
    import websocket
except ImportError:
    # chrome headless tests will be skipped
    websocket = None


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

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Handling of the events sent by Chrome: the console messages, the exceptions and the requests."""

from __future__ import annotations

import contextlib
import logging
import re
import typing
from concurrent.futures import CancelledError, InvalidStateError
from ..utils import HOST, IGNORED_MSGS, _logger, run

if typing.TYPE_CHECKING:
    pass

from .exceptions import ChromeBrowserException
from .transport import websocket

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

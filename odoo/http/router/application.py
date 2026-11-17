"""The WSGI application: the static files, the routing maps, and the dispatch of the requests to the serving functions."""

from __future__ import annotations

import functools
import logging
import os.path
import threading
import typing
from os.path import join as opj
from urllib.parse import urlparse
import werkzeug.routing
from werkzeug.exceptions import (
    HTTPException,
)
from werkzeug.urls import url_encode  # TODO: use urllib
from odoo.exceptions import AccessError, UserError
from odoo.modules.module import (
    Manifest,
    initialize_sys_path,
)
from odoo.tools import config, file_path
from odoo.tools.misc import submap
from .. import request, request_var
from ..dispatcher import (
    conceal_debug_traceback,
)
from ..requestlib import (
    HTTPRequest,
    Request,
)
from ..response import Response
from ..routing_map import ROUTING_KEYS, _generate_routing_rules
from ..session import SessionExpiredException, logout

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from wsgiref.types import StartResponse, WSGIEnvironment

from .databases import RegistryError
from .setup import _get_profiler_context_manager, _set_session_and_dbname

_logger = logging.getLogger('odoo.http')


try:
    from werkzeug.middleware.proxy_fix import ProxyFix as ProxyFix_
    ProxyFix = functools.partial(ProxyFix_, x_for=1, x_proto=1, x_host=1)
except ImportError:
    from werkzeug.contrib.fixers import ProxyFix


class Application:
    """ Odoo WSGI application """
    # See also: https://www.python.org/dev/peps/pep-3333

    def initialize(self) -> None:
        """
        Initialize the application.

        This is to be called when setting up a WSGI application after
        initializing the configuration values.
        """
        initialize_sys_path()
        from odoo.service.server import load_server_wide_modules  # noqa: PLC0415
        load_server_wide_modules()

    def static_path(self, module_name: str) -> str | None:
        """
        Map module names to their absolute ``static`` path on the file
        system.
        """
        manifest = Manifest.for_addon(module_name, display_warning=False)
        return manifest.static_path if manifest is not None else None

    def get_static_file(self, url: str, host: str = '') -> str | None:
        """
        Get the full-path of the file if the url resolves to a local
        static file, otherwise return None.

        Without the second host parameters, ``url`` must be an absolute
        path, others URLs are considered faulty.

        With the second host parameters, ``url`` can also be a full URI
        and the authority found in the URL (if any) is validated against
        the given ``host``.
        """

        netloc, path = urlparse(url)[1:3]
        path = os.path.normpath(os.path.normcase(path))
        try:
            path_netloc, module, static, resource = path.split(os.sep, 3)
        except ValueError:
            return None

        if ((netloc and netloc != host) or (path_netloc and path_netloc != host)):
            return None

        if not (static == 'static' and resource):
            return None

        static_path = self.static_path(module)
        if not static_path:
            return None

        try:
            return file_path(opj(static_path, resource))
        except FileNotFoundError:
            return None

    @functools.cached_property
    def nodb_routing_map(self):
        nodb_routing_map = werkzeug.routing.Map(strict_slashes=False, converters=None)
        for url, endpoint in _generate_routing_rules([''] + config['server_wide_modules'], nodb_only=True):
            routing = submap(endpoint.routing, ROUTING_KEYS)
            if routing['methods'] is not None and 'OPTIONS' not in routing['methods']:
                routing['methods'] = [*routing['methods'], 'OPTIONS']
            rule = werkzeug.routing.Rule(url, endpoint=endpoint, **routing)
            rule.merge_slashes = False
            nodb_routing_map.add(rule)

        return nodb_routing_map

    def get_db_router(self, db: str | None) -> werkzeug.routing.Map:
        if not db:
            return self.nodb_routing_map
        return request.env['ir.http'].routing_map()

    def set_csp(self, response: Response) -> None:
        headers = response.headers
        headers['X-Content-Type-Options'] = 'nosniff'

        if 'Content-Security-Policy' in headers:
            return

        if not headers.get('Content-Type', '').startswith('image/'):
            return

        headers['Content-Security-Policy'] = "default-src 'none'"

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        """
        WSGI application entry point.

        :param environ: container for CGI environment variables
            such as the request HTTP headers, the source IP address and
            the body as an io file.
        :param start_response: function provided by the WSGI
            server that this application must call in order to send the
            HTTP response status line and the response headers.
        """
        if config['proxy_mode'] and environ.get("HTTP_X_FORWARDED_HOST"):
            # It is done in our wsgi server already, but people might be
            # using another wsgi server.
            # The ProxyFix middleware has a side effect of updating the
            # environ, see https://github.com/pallets/werkzeug/pull/2184
            def fake_app(environ, start_response):
                return []
            def fake_start_response(status, headers):  # noqa: E301, E306
                return
            ProxyFix(fake_app)(environ, fake_start_response)

        with HTTPRequest(environ) as httprequest:
            request = Request(httprequest)
            request_reset = request_var.set(request)
            try:
                _set_session_and_dbname(request)
                threading.current_thread().url = httprequest.url

                if self.get_static_file(httprequest.path):
                    response = serve_static(request)
                elif request.db:
                    try:
                        with _get_profiler_context_manager(request):
                            response = serve_db(request)
                    except RegistryError as e:
                        _logger.warning("Database or registry unusable, trying without", exc_info=e.__cause__)
                        # TODO: move those bits in a dedicated function
                        request.db = None
                        logout(request.session)
                        if (httprequest.path.startswith('/odoo/')
                            or httprequest.path in (
                                '/odoo', '/web', '/web/login', '/test_http/ensure_db',
                            )):
                            # ensure_db() protected routes, remove ?db= from the query string
                            args_nodb = request.httprequest.args.copy()
                            args_nodb.pop('db', None)
                            request.reroute(httprequest.path, url_encode(args_nodb))
                        response = serve_nodb(request)
                else:
                    response = serve_nodb(request)
                return response(environ, start_response)

            except Exception as exc:
                # Logs the error here so the traceback starts with ``__call__``.
                if hasattr(exc, 'loglevel'):
                    _logger.log(exc.loglevel, exc, exc_info=getattr(exc, 'exc_info', None))
                elif isinstance(exc, HTTPException):
                    pass
                elif isinstance(exc, SessionExpiredException):
                    _logger.info(exc)
                elif isinstance(exc, AccessError):
                    _logger.warning(exc, exc_info='access' in config['dev_mode'])
                elif isinstance(exc, UserError):
                    _logger.warning(exc)
                else:
                    _logger.exception("Exception during request handling.")

                # Ensure there is always a WSGI handler attached to the exception.
                if not hasattr(exc, 'error_response'):
                    exc.error_response = request.dispatcher.handle_error(
                        conceal_debug_traceback.without_traceback_if_concealed(exc))

                return exc.error_response(environ, start_response)

            finally:
                request_var.reset(request_reset)


root = Application()


# imported at the end: the module of the other side imports this one
from .serve import serve_db, serve_nodb, serve_static

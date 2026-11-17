"""The serving of the requests by their kind: the static files, the requests without database and the requests with a database."""

from __future__ import annotations

import functools
import logging
import threading
import typing
import psycopg2
from psycopg2.errors import ReadOnlySqlTransaction
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
)
from werkzeug.security import safe_join
from odoo.api import Environment
from odoo.modules.registry import Registry
from odoo.tools import file_open
from ..dispatcher import (
    HttpDispatcher,
    conceal_debug_traceback,
)
from ..requestlib import (
    Request,
)
from ..response import Response
from ..retrying import retrying
from ..stream import STATIC_CACHE, Stream

if typing.TYPE_CHECKING:
    from ..routing_map import Endpoint

from .application import root
from .databases import RegistryError
from .ir_http import _serve_ir_http_fallback, serve_ir_http
from .setup import _set_request_dispatcher

_logger = logging.getLogger('odoo.http')


def serve_static(request: Request) -> Response:
    """ Serve a static file from the file system. """
    module, _, path = request.httprequest.path[1:].partition('/static/')
    try:
        directory = root.static_path(module)
        if not directory:
            raise NotFound(f'Module "{module}" not found.\n')
        filepath = safe_join(directory, path)
        debug = (
            'assets' in request.session.debug and
            ' wkhtmltopdf ' not in request.httprequest.user_agent.string
        )
        res = Stream.from_path(filepath, public=True).get_response(
            max_age=0 if debug else STATIC_CACHE,
            content_security_policy=None,
        )
        root.set_csp(res)
        return res
    except OSError:  # cover both missing file and invalid permissions
        raise NotFound(f'File "{path}" not found in module {module}.\n')


def serve_nodb(request: Request) -> Response:
    """
    Dispatch the request to its matching controller in a
    database-free environment.
    """
    try:
        router = root.nodb_routing_map.bind_to_environ(request.httprequest.environ)
        try:
            rule, args = router.match(return_rule=True)
        except NotFound as exc:
            with file_open(f'{__file__}/../not_found_nodb.html', 'rb') as f:
                exc.response = Response(f.read(), status=exc.code, mimetype='text/html')
            raise
        _set_request_dispatcher(request, rule)
        request.dispatcher.pre_dispatch(rule, args)
        endpoint: Endpoint = rule.endpoint  # type: ignore
        response = request.dispatcher.dispatch(endpoint, args)
        request.dispatcher.post_dispatch(response)
        return response
    except HTTPException as exc:
        if exc.code is not None:
            raise
        # Valid response returned via werkzeug.exceptions.abort
        response = exc.get_response()
        HttpDispatcher(request).post_dispatch(response)
        return response


def serve_db(request: Request) -> Response:
    """ Load the ORM and use it to process the request. """
    # reuse the same cursor for building, checking the registry, for
    # matching the controller endpoint and serving the data
    cr = None
    try:
        # get the registry and cursor (RO)
        try:
            registry = Registry(request.db)
            cr = registry.cursor(readonly=True)
            # check signaling
            request.env = Environment(cr, request.session.uid, request.session.context)
            request.update_context(host_id=request.env['ir.http']._get_host_id_from_domain(request.httprequest.host))

            request.registry = request.env.registry
        except (AttributeError, psycopg2.OperationalError, psycopg2.ProgrammingError) as e:
            raise RegistryError(f"Cannot get registry {request.db}") from e

        # find the controller endpoint to use
        try:
            rule, args = request.registry['ir.http']._match(request.httprequest.path)
        except NotFound as not_found_exc:
            # no controller endpoint matched -> fallback or 404
            serve_func = functools.partial(_serve_ir_http_fallback, request, not_found_exc)
            readonly = True
        else:
            # a controller endpoint matched -> dispatch it the request
            _set_request_dispatcher(request, rule)
            serve_func = functools.partial(serve_ir_http, request, rule, args)
            endpoint: Endpoint = rule.endpoint  # type: ignore
            readonly = endpoint.routing['readonly']
            if callable(readonly):
                readonly = readonly(endpoint.func.__self__, rule, args)
        # update the parent cache for the route mapping to make it available as
        # soon as possible and don't lose it if there are invalidations
        for layer in request.env.transaction.ormcaches__.values():
            layer.update_parent()

        # keep on using the RO cursor when a readonly route matched,
        # and for serve fallback
        if readonly and cr.readonly:
            threading.current_thread().cursor_mode = 'ro'
            try:
                return retrying(serve_func, env=request.env)
            except ReadOnlySqlTransaction as exc:
                # although the controller is marked read-only, it
                # attempted a write operation, try again using a
                # read/write cursor
                _logger.warning("%s, retrying with a read/write cursor", exc.args[0].rstrip(), exc_info=True)
                threading.current_thread().cursor_mode = 'ro->rw'
            except Exception as exc:  # noqa: BLE001
                raise _update_served_exception(request, exc)
        else:
            threading.current_thread().cursor_mode = 'rw'

        # we must use a RW cursor when a read/write route matched, or
        # there was a ReadOnlySqlTransaction error
        if cr.readonly:
            cr.close()
            cr = request.env.registry.cursor()
        else:
            # the cursor is already a RW cursor, start a new transaction
            # that will avoid repeatable read serialization errors because
            # check signaling is not done in `retrying` and that function
            # would just succeed the second time
            cr.rollback()
        assert not cr.readonly
        request.env = request.env(cr=cr)
        try:
            return retrying(serve_func, env=request.env)
        except Exception as exc:  # noqa: BLE001
            raise _update_served_exception(request, exc)
    except HTTPException as exc:
        if exc.code is not None:
            raise
        # Valid response returned via werkzeug.exceptions.abort
        response = exc.get_response()
        HttpDispatcher(request).post_dispatch(response)
        return response
    finally:
        request.env = None
        if cr is not None:
            cr.close()


def _update_served_exception(request: Request, exc: Exception) -> Exception:
    if isinstance(exc, HTTPException) and exc.code is None:
        return exc  # bubble up to _serve_db
    if not hasattr(exc, 'error_response'):
        exc.error_response = request.registry['ir.http']._handle_error(
            conceal_debug_traceback.without_traceback_if_concealed(exc))
    return exc

"""The serving of the requests through the routes of the ir.http model, with the fallback when no route matches."""

from __future__ import annotations

import typing
import werkzeug.routing
from werkzeug.exceptions import (
    NotFound,
)
from ..requestlib import (
    Request,
)
from ..response import Response

if typing.TYPE_CHECKING:
    pass


def _serve_ir_http_fallback(request: Request, not_found: NotFound) -> Response:
    """
    Called when no controller match the request path. Delegate to
    ``ir.http._serve_fallback`` to give modules the opportunity to
    find an alternative way to serve the request. In case no module
    provided a response, a generic 404 - Not Found page is returned.
    """
    request.params = request.get_http_params()
    request.registry['ir.http']._auth_method_public({})
    response = request.registry['ir.http']._serve_fallback()
    if response:
        request.registry['ir.http']._post_dispatch(response)
        return response

    no_fallback = NotFound()
    no_fallback.__context__ = not_found  # During handling of {not_found}, {no_fallback} occurred:
    no_fallback.error_response = request.registry['ir.http']._handle_error(no_fallback)
    raise no_fallback


def serve_ir_http(request: Request, rule: werkzeug.routing.Rule, args) -> Response:
    """
    Called when a controller match the request path. Delegate to
    ``ir.http`` to serve a response.
    """
    request.registry['ir.http']._authenticate(rule.endpoint)
    request.registry['ir.http']._pre_dispatch(rule, args)
    response = request.dispatcher.dispatch(rule.endpoint, args)
    request.registry['ir.http']._post_dispatch(response)
    return response

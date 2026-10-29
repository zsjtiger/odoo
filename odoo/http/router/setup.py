"""The setup of the requests before they are served: the profiler, the session and the database, and the request dispatcher."""

from __future__ import annotations

import datetime as dt
import logging
import threading
import typing
from contextlib import nullcontext
import werkzeug.routing
from werkzeug.exceptions import (
    Forbidden,
    UnsupportedMediaType,
)
import odoo.modules.db
from odoo.tools.profiling import profiler
from ..dispatcher import (
    _dispatchers,
)
from ..requestlib import (
    Request,
    is_cors_preflight,
)
from ..session import get_default_session, logout, session_store

if typing.TYPE_CHECKING:
    from ..routing_map import Endpoint

from .databases import db_filter, db_list

_logger = logging.getLogger('odoo.http')


def _get_profiler_context_manager(request: Request) -> typing.ContextManager:
    """
    Get a profiler when the profiling is enabled and the requested
    URL is profile-safe. Otherwise, get a context-manager that does
    nothing.
    """
    if request.session.get('profile_session') and request.db:
        if request.session['profile_expiration'] < str(dt.datetime.now()):
            # avoid having session profiling for too long if user forgets to disable profiling
            request.session['profile_session'] = None
            _logger.warning("Profiling expiration reached, disabling profiling")
        elif 'set_profiling' in request.httprequest.path:
            _logger.debug("Profiling disabled on set_profiling route")
        elif request.httprequest.path.startswith('/websocket'):
            _logger.debug("Profiling disabled for websocket")
        elif odoo.evented:
            # only longpolling should be in a evented server, but this is an additional safety
            _logger.debug("Profiling disabled for evented server")
        else:
            try:
                return profiler.Profiler(
                    db=request.db,
                    description=request.httprequest.full_path,
                    profile_session=request.session['profile_session'],
                    collectors=request.session['profile_collectors'],
                    params=request.session['profile_params'],
                )._get_cm_proxy()
            except Exception:
                _logger.exception("Failure during Profiler creation")
                request.session['profile_session'] = None

    return nullcontext()


def _set_session_and_dbname(request: Request) -> None:
    sid = request.httprequest.cookies.get('session_id', '')
    session = session_store().get(sid, keep_sid=True)

    for key, val in get_default_session().items():
        session.setdefault(key, val)
    if not session.context.get('lang'):
        session.context['lang'] = request.default_lang()

    dbname = None
    host = request.httprequest.environ['HTTP_HOST']
    header_dbname = request.httprequest.headers.get('X-Odoo-Database')
    if session.db and db_filter([session.db], host=host):
        dbname = session.db
        if header_dbname and header_dbname != dbname:
            e = ("Cannot use both the session_id cookie and the "
                    "x-odoo-database header.")
            raise Forbidden(e)
    elif header_dbname:
        session.can_save = False  # stateless
        if db_filter([header_dbname], host=host):
            dbname = header_dbname
    else:
        all_dbs = db_list(force=True, host=host)
        if len(all_dbs) == 1:
            dbname = all_dbs[0]  # monodb

    if session.db != dbname:
        if session.db:
            _logger.warning("Logged into database %r, but dbfilter rejects it; logging session out.", session.db)
            logout(session, keep_db=False)
        session.db = dbname

    session.is_dirty = False
    request.session = session
    request.db = dbname
    threading.current_thread().sess_id = request.session.sid[:8]


def _set_request_dispatcher(request: Request, rule: werkzeug.routing.Rule):
    endpoint: Endpoint = rule.endpoint  # type: ignore
    routing = endpoint.routing
    dispatcher_cls = _dispatchers[routing['type']]
    if (not is_cors_preflight(request, endpoint)
        and not dispatcher_cls.is_compatible_with(request)):
        compatible_dispatchers = [
            disp.routing_type
            for disp in _dispatchers.values()
            if disp.is_compatible_with(request)
        ]
        e = (f"Request inferred type is compatible with {compatible_dispatchers} "
                f"but {routing['routes'][0]!r} is type={routing['type']!r}.\n\n"
                "Please verify the Content-Type request header and try again.")
        # werkzeug doesn't let us add headers to UnsupportedMediaType
        # so use the following (ugly) to still achieve what we want
        res = UnsupportedMediaType(e).get_response()
        res.headers['Accept'] = ', '.join(dispatcher_cls.mimetypes)
        raise UnsupportedMediaType(response=res)
    request.dispatcher = dispatcher_cls(request)

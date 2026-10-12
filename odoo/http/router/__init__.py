# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The routing of the HTTP requests: the databases, the RPC dispatch, the WSGI application, the serving of the requests and their setup. The names are re-exported here."""

from .application import Application, ProxyFix, root
from .databases import RegistryError, db_filter, db_list
from .rpc import dispatch_rpc
from .serve import _update_served_exception, serve_db, serve_nodb, serve_static
from .ir_http import _serve_ir_http_fallback, serve_ir_http
from .setup import _get_profiler_context_manager, _set_request_dispatcher, _set_session_and_dbname

"""The dispatch of the RPC calls to the services."""

from __future__ import annotations

import threading
import typing
from .. import request_var

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def dispatch_rpc(service_name: str, method: str, params: Mapping[str, typing.Any]) -> typing.Any:
    """
    Perform a RPC call.

    :param service_name: either "common", "db" or "object".
    :param method: the method name of the given service to execute
    :param params: the keyword arguments for method call
    :return: the return value of the called method
    """
    import odoo.service  # noqa: PLC0415

    if service_name == 'object':
        dispatch = odoo.service.model.dispatch
    elif service_name == 'common':
        dispatch = odoo.service.common.dispatch
    else:
        raise ValueError(f"Invalid service name: {service_name}")

    # Remove the request to simulate that the call does not come from HTTP
    request_reset = request_var.set(None)
    try:
        threading.current_thread().uid = None
        threading.current_thread().dbname = None
        return dispatch(method, params)
    finally:
        request_var.reset(request_reset)

"""The databases of the requests: the lists of the databases, their filtering by host, and the errors of their registries."""

from __future__ import annotations

import re
import typing
from psycopg2.errors import OperationalError
import odoo.modules.db
from odoo.tools import config
from .. import request

if typing.TYPE_CHECKING:
    from collections.abc import Iterable


def db_list(force: bool = False, host: str | None = None) -> list[str]:
    """
    Get the list of available databases.

    :param bool force: See :func:`~odoo.modules.db.list_dbs`
    :param host: The Host used to replace %h and %d in the dbfilters
        regexp. Taken from the current request when omitted.
    :returns: the list of available databases
    :rtype: List[str]
    """
    try:
        dbs = odoo.modules.db.list_dbs(force=force)
    except OperationalError:
        return []
    return db_filter(dbs, host)


def db_filter(dbs: Iterable[str], host: str | None = None) -> list[str]:
    """
    Return the subset of ``dbs`` that match the dbfilter or the dbname
    server configuration. In case neither are configured, return ``dbs``
    as-is.

    :param Iterable[str] dbs: The list of database names to filter.
    :param host: The Host used to replace %h and %d in the dbfilters
        regexp. Taken from the current request when omitted.
    :returns: The original list filtered.
    :rtype: List[str]
    """

    if config['dbfilter']:
        #        host
        #     -----------
        # www.example.com:80
        #     -------
        #     domain
        if host is None:
            host = request.httprequest.environ.get('HTTP_HOST', '')
        host = host.partition(':')[0]
        host = host.removeprefix('www.')
        domain = host.partition('.')[0]

        dbfilter_re = re.compile(
            config["dbfilter"].replace(R"%h", re.escape(host))
                              .replace(R"%d", re.escape(domain)))
        return [db for db in dbs if dbfilter_re.match(db)]

    if config['db_name']:
        # In case --db-filter is not provided and --database is passed, Odoo will
        # use the value of --database as a comma separated list of exposed databases.
        return sorted(set(config['db_name']).intersection(dbs))

    return list(dbs)


class RegistryError(RuntimeError):
    pass

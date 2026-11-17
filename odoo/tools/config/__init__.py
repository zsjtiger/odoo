# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The configuration of the server: the options, their parsing from the command
line and the configuration files, and the values of the options.

``config`` is the configuration of the running server. The names of the former
module are re-exported here.
"""
from .options import (
    ALL_DEV_MODE, DEFAULT_COLOR_SPEC, DEFAULT_SERVER_WIDE_MODULES, EMPTY,
    REQUIRED_SERVER_WIDE_MODULES, _Empty, _FileOnlyOption, _OdooOption, _PosixOnlyOption,
    OdooOptionParser, _deduplicate_loggers, crypt_context, _dangerous_logger,
)
from .manager import config, configmanager

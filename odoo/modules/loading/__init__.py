# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The loading of the modules, split by concern: the data, the module graph and the loader. The names are re-exported here."""

from .. import db as modules_db
from ..migration import MigrationManager
from ..module import adapt_version, initialize_sys_path, load_openerp_module
from ..module_graph import ModuleGraph
from ..registry import Registry
from .loader import _FORCED_MODULES, _check_module_names, load_modules, reset_modules_state
from .data import force_demo, load_data, load_demo
from .graph import load_module_graph

# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The modules of the applications: the modules, their categories, dependencies and exclusions. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import ACTION_DICT, STATES, XML_DECLARATION, assert_log_admin_access, backup
from .rst import MyFilterMessages, MyWriter
from .category import IrModuleCategory
from .module import IrModuleModule
from .dependency import DEP_STATES, IrModuleModuleDependency
from .exclusion import IrModuleModuleExclusion

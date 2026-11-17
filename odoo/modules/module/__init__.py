# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Utility functions to manage module manifest files and discovery, split by concern. The names are re-exported here."""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from unittest import TestCase

from .loader import TYPED_FIELD_DEFINITION_RE, load_openerp_module, load_script
from .paths import UpgradeHook, get_module_path, get_resource_from_path, initialize_sys_path
from .dependencies import InvalidRequirement, MissingDependency, Requirement, check_python_external_dependency
from .manifest import MANIFEST_NAMES, MODULE_NAME_RE, Manifest, README, _DEFAULT_MANIFEST, _load_manifest, get_manifest, get_module_icon, get_modules
from .versions import adapt_version, check_version

# the state of the tests, set by the test suite and read by the other modules
current_test: TestCase | None = None

__all__ = [
    'Manifest',
    'adapt_version',
    'get_manifest',
    'get_module_path',
    'get_modules',
    'get_resource_from_path',
    'initialize_sys_path',
    'load_openerp_module',
]

"""The paths of the modules: the addons path, the upgrade hook, and the lookup of the modules and of their resources."""

from __future__ import annotations

import importlib
import os
import re
import sys
import typing
import odoo.tools as tools
import odoo.upgrade
import odoo.addons

if typing.TYPE_CHECKING:
    pass

from .manifest import Manifest

class UpgradeHook:
    """Makes the legacy `migrations` package being `odoo.upgrade`"""

    def find_spec(self, fullname, path=None, target=None):
        if re.match(r"^odoo\.addons\.base\.maintenance\.migrations\b", fullname):
            # We can't trigger a DeprecationWarning in this case.
            # In order to be cross-versions, the multi-versions upgrade scripts (0.0.0 scripts),
            # the tests, and the common files (utility functions) still needs to import from the
            # legacy name.
            return importlib.util.spec_from_loader(fullname, self)

    def load_module(self, name):
        assert name not in sys.modules

        canonical_upgrade = name.replace("odoo.addons.base.maintenance.migrations", "odoo.upgrade")

        if canonical_upgrade in sys.modules:
            mod = sys.modules[canonical_upgrade]
        else:
            mod = importlib.import_module(canonical_upgrade)

        sys.modules[name] = mod

        return sys.modules[name]


def initialize_sys_path() -> None:
    """
    Setup the addons path ``odoo.addons.__path__`` with various defaults
    and explicit directories.
    """
    for path in (
        # tools.config.addons_base_dir,  # already present
        tools.config.addons_data_dir,
        *tools.config['addons_path'],
        tools.config.addons_community_dir,
    ):
        if os.access(path, os.R_OK) and path not in odoo.addons.__path__:
            odoo.addons.__path__.append(path)

    # hook odoo.upgrade on upgrade-path
    legacy_upgrade_path = os.path.join(tools.config.addons_base_dir, 'base/maintenance/migrations')
    for up in tools.config['upgrade_path'] or [legacy_upgrade_path]:
        if up not in odoo.upgrade.__path__:
            odoo.upgrade.__path__.append(up)

    # create decrecated module alias from odoo.addons.base.maintenance.migrations to odoo.upgrade
    spec = importlib.machinery.ModuleSpec("odoo.addons.base.maintenance", None, is_package=True)
    maintenance_pkg = importlib.util.module_from_spec(spec)
    maintenance_pkg.migrations = odoo.upgrade  # type: ignore
    sys.modules["odoo.addons.base.maintenance"] = maintenance_pkg
    sys.modules["odoo.addons.base.maintenance.migrations"] = odoo.upgrade

    # hook for upgrades and namespace freeze
    if not getattr(initialize_sys_path, 'called', False):  # only initialize once
        odoo.addons.__path__._path_finder = lambda *a: None  # prevent path invalidation
        odoo.upgrade.__path__._path_finder = lambda *a: None  # prevent path invalidation
        sys.meta_path.insert(0, UpgradeHook())
        initialize_sys_path.called = True  # type: ignore


def get_module_path(module: str, display_warning: bool = True) -> str | None:
    """Return the path of the given module.

    Search the addons paths and return the first path where the given
    module is found. If downloaded is True, return the default addons
    path if nothing else is found.

    """
    # TODO deprecate
    mod = Manifest.for_addon(module, display_warning=display_warning)
    return mod.path if mod else None


def get_resource_from_path(path: str) -> tuple[str, str, str] | None:
    """Tries to extract the module name and the resource's relative path
    out of an absolute resource path.

    If operation is successful, returns a tuple containing the module name, the relative path
    to the resource using '/' as filesystem seperator[1] and the same relative path using
    os.path.sep seperators.

    [1] same convention as the resource path declaration in manifests

    :param path: absolute resource path

    :rtype: tuple
    :return: tuple(module_name, relative_path, os_relative_path) if possible, else None
    """
    resource = None
    sorted_paths = sorted(odoo.addons.__path__, key=len, reverse=True)
    for adpath in sorted_paths:
        # force trailing separator
        adpath = os.path.join(adpath, "")
        if os.path.commonprefix([adpath, path]) == adpath:
            resource = path.replace(adpath, "", 1)
            break

    if resource:
        relative = resource.split(os.path.sep)
        if not relative[0]:
            relative.pop(0)
        module = relative.pop(0)
        return (module, '/'.join(relative), os.path.sep.join(relative))
    return None

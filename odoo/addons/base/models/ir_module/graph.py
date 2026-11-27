# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The dependencies of the modules: the external dependencies, the modules to load and the dependency graph."""

import platform
import warnings
from odoo import _, modules
from odoo.exceptions import UserError
from odoo.modules.module import MissingDependency
from odoo.tools import SQL


def _get_modules_to_load_domain(self):
    """ Domain to retrieve the modules that should be loaded by the registry. """
    return [('state', '=', 'installed')]


def check_external_dependencies(self, module_name, newstate='to install'):
    manifest = modules.Manifest.for_addon(module_name)
    if not manifest:
        return  # unavailable module, there is no point in checking dependencies
    try:
        manifest.check_manifest_dependencies()
    except MissingDependency as e:
        if newstate == 'to install':
            msg = _('Unable to install module "%(module)s" because an external dependency is not met: %(dependency)s', module=module_name, dependency=e.dependency)
        elif newstate == 'to upgrade':
            msg = _('Unable to upgrade module "%(module)s" because an external dependency is not met: %(dependency)s', module=module_name, dependency=e.dependency)
        else:
            msg = _('Unable to process module "%(module)s" because an external dependency is not met: %(dependency)s', module=module_name, dependency=e.dependency)

        install_package = None
        if platform.system() == 'Linux':
            distro = platform.freedesktop_os_release()
            id_likes = {distro['ID'], *distro.get('ID_LIKE', '').split()}
            if 'debian' in id_likes or 'ubuntu' in id_likes:
                if package := manifest['external_dependencies'].get('apt', {}).get(e.dependency):
                    install_package = f'apt install {package}'

        if install_package:
            msg += _("\nIt can be installed running: %s", install_package)

        raise UserError(msg) from e


def downstream_dependencies(self, known_deps=None,
                            exclude_states=('uninstalled', 'uninstallable', 'to remove')):
    """ Return the modules that directly or indirectly depend on the modules
        in `self`, and that satisfy the `exclude_states` filter.
        """
    if not self:
        return self
    self.flush_model(['name', 'state'])
    self.env['ir.module.module.dependency'].flush_model(['module_id', 'name'])
    known_deps = known_deps or self.browse()
    query = """ SELECT DISTINCT m.id
                    FROM ir_module_module_dependency d
                    JOIN ir_module_module m ON (d.module_id=m.id)
                    WHERE
                        d.name IN (SELECT name from ir_module_module where id in %s) AND
                        m.state NOT IN %s AND
                        m.id NOT IN %s """
    self.env.cr.execute(query, (tuple(self.ids), tuple(exclude_states), tuple(known_deps.ids or self.ids)))
    new_deps = self.browse([row[0] for row in self.env.cr.fetchall()])
    missing_mods = new_deps - known_deps
    known_deps |= new_deps
    if missing_mods:
        known_deps |= missing_mods.downstream_dependencies(known_deps, exclude_states)
    return known_deps


def upstream_dependencies(self, known_deps=None,
                          exclude_states=('installed', 'uninstallable', 'to remove')):
    """ Return the dependency tree of modules of the modules in `self`, and
        that satisfy the `exclude_states` filter.
        """
    if not self:
        return self
    if known_deps is not None:
        warnings.warn(
            "The `known_deps` parameter is deprecated since Odoo 20.",
            category=DeprecationWarning,
            stacklevel=2,
        )
    self.flush_model(['name', 'state'])
    self.env['ir.module.module.dependency'].flush_model(['module_id', 'name'])
    self.env.cr.execute(SQL(
        """
            WITH RECURSIVE dependencies AS (
                SELECT m.id
                FROM ir_module_module_dependency d
                JOIN ir_module_module m ON (d.name = m.name)
                WHERE d.module_id = any(%(ids)s) AND m.state != all(%(states)s)
            UNION
                SELECT m.id
                FROM dependencies
                JOIN ir_module_module_dependency d ON (d.module_id = dependencies.id)
                JOIN ir_module_module m ON (d.name = m.name)
                WHERE m.state != all(%(states)s)
            )
            SELECT id FROM dependencies WHERE id != any(%(ids)s)
            """,
        ids=self.ids,
        states=list(exclude_states),
    ))
    return self.browse(row[0] for row in self.env.cr.fetchall())

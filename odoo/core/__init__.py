# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Infrastructure of the Odoo server: bootstrap, library patches and logging.

Importing this package registers the aliases of the modules that have been
moved, so that code importing them by their former name keeps working. An
alias and its target are the same module object, which keeps ``mock.patch``
on the former names working.
"""
import importlib
import importlib.abc
import importlib.util
import sys

# former module name -> current module name
ALIASES = {
    'odoo.init': 'odoo.core.bootstrap',
    'odoo._monkeypatches': 'odoo.core.patches',
    'odoo.logging': 'odoo.core.logging',
    'odoo.loglevels': 'odoo.core.logging',
    'odoo.netsvc': 'odoo.core.logging',
    'odoo.sql_db': 'odoo.orm.sql_db',
    'odoo.tools.cache': 'odoo.orm.cache',  # deprecated since 20.0
    'odoo.tools.cloc': 'odoo.modules.cloc',
    'odoo.tools.duplicate': 'odoo.cli.duplicate',
    'odoo.tools.view_validation': 'odoo.orm.view_validation',
    'odoo.upgrade_code': 'odoo.cli.upgrade_code',
}


def resolve_alias(fullname):
    """Return the current name of the module ``fullname``, or ``None`` if it
    has not been moved. Submodules of moved packages are resolved too.
    """
    name, sep, rest = fullname, '', ''
    while name:
        if name in ALIASES:
            return ALIASES[name] + sep + rest
        name, dot, last = name.rpartition('.')
        rest = last + dot + rest if rest else last
        sep = '.'
    return None


class AliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import hook that serves a moved module under its former name."""

    def find_spec(self, fullname, path=None, target=None):
        target_name = resolve_alias(fullname)
        if target_name is None:
            return None
        spec = importlib.util.find_spec(target_name)
        if spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, self, is_package=spec.submodule_search_locations is not None,
        )

    def create_module(self, spec):
        return importlib.import_module(resolve_alias(spec.name))

    def exec_module(self, module):
        pass


if not any(isinstance(finder, AliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, AliasFinder())

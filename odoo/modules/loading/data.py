"""The loading of the data of the modules: the data files, the demo data and the forced demo data."""

from __future__ import annotations

import logging
import typing
import traceback
from odoo.tools.loading.convert import convert_file, IdRef, ConvertMode as LoadMode
from ..module_graph import ModuleGraph
from ..registry import Registry

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from ..module_graph import ModuleNode
    LoadKind = typing.Literal['data', 'demo']


_logger = logging.getLogger('odoo.modules.loading')


def load_data(env: Environment, idref: IdRef, mode: LoadMode, kind: LoadKind, package: ModuleNode) -> bool:
    """
    noupdate is False, unless it is demo data

    :returns: Whether a file was loaded
    """
    files = set()
    for filename in package.manifest[kind]:
        if filename in files:
            _logger.warning("File %s is imported twice in module %s %s", filename, package.name, kind)
        files.add(filename)

        _logger.info("loading %s/%s", package.name, filename)
        convert_file(env, package.name, filename, idref, mode, noupdate=kind == 'demo')
        env.cr.flush()  # run precommit hooks

    return bool(files)


def load_demo(env: Environment, package: ModuleNode, idref: IdRef, mode: LoadMode) -> bool:
    """
    Loads demo data for the specified package.
    """

    try:
        if package.manifest.get('demo'):
            _logger.info("Module %s: loading demo", package.name)
            with env.cr.savepoint(flush=False):
                load_data(env(su=True, context=dict(env.context, install_demo=True)), idref, mode, kind='demo', package=package)
        return True
    except Exception:  # noqa: BLE001
        # If we could not install demo data for this module
        _logger.warning(
            "Module %s demo data failed to install, installed without demo data",
            package.name, exc_info=True)

        todo = env.ref('base.demo_failure_todo', raise_if_not_found=False)
        Failure = env.get('ir.demo_failure')
        if todo and Failure is not None:
            todo.state = 'open'
            Failure.create({'module_id': package.id, 'error': traceback.format_exc()})
        return False


def force_demo(env: Environment) -> None:
    """
    Forces the `demo` flag on all modules, and installs demo data for all installed modules.
    """
    assert env.registry.ready
    env['ir.config_parameter'].sudo().set_int('auth_password_policy.minlength', 4)
    env.cr.execute('UPDATE ir_module_module SET demo=True')
    env.cr.execute(
        "SELECT name FROM ir_module_module WHERE state IN ('installed', 'to upgrade', 'to remove')"
    )
    module_list = [name for (name,) in env.cr.fetchall()]
    graph = ModuleGraph(env.cr, mode='load')
    graph.extend(module_list)

    for package in graph:
        load_demo(env, package, {}, 'init')

    env['ir.module.module'].invalidate_model(['demo'])

    # If demo data triggered module state changes (to install/upgrade/remove),
    # commit and rebuild registry to process button_install/upgrade calls.
    if env['ir.module.module'].search_count([('state', 'in', ('to install', 'to upgrade', 'to remove'))], limit=1):
        env.cr.commit()
        Registry.new(env.cr.dbname, update_module=True)
        env.cr.rollback()

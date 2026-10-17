"""The loading of the modules in the order of their graph: the models, the data and the post-load hooks of each module."""

from __future__ import annotations

import logging
import sys
import time
import typing
import odoo.orm.database.sql_db
from odoo import tools
from ..migration import MigrationManager
from ..module import adapt_version, load_openerp_module
from ..module_graph import ModuleGraph

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.tests.result import OdooTestResult
    LoadKind = typing.Literal['data', 'demo']

from .data import load_data, load_demo

_logger = logging.getLogger('odoo.modules.loading')


def load_module_graph(
    env: Environment,
    graph: ModuleGraph,
    update_module: bool = False,
    report: OdooTestResult | None = None,
    install_demo: bool = True,
) -> None:
    """ Load, upgrade and install not loaded module nodes in the ``graph`` for ``env.registry``

       :param env:
       :param graph: graph of module nodes to load
       :param update_module: whether to update modules or not
       :param report:
       :param install_demo: whether to attempt installing demo data for newly installed modules
    """
    registry = env.registry
    assert isinstance(env.cr, odoo.orm.database.sql_db.Cursor), "Need for a real Cursor to load modules"
    migrations = MigrationManager(env.cr, graph)
    module_count = len(graph)
    _logger.info('loading %d modules...', module_count)

    # register, instantiate and initialize models for each modules
    t0 = time.time()
    loading_extra_query_count = odoo.orm.database.sql_db.cursor.sql_counter
    loading_cursor_query_count = env.cr.sql_log_count

    models_updated = set()

    for index, package in enumerate(graph, 1):
        module_name = package.name
        module_id = package.id

        if module_name in registry._init_modules:
            continue

        module_t0 = time.time()
        module_cursor_query_count = env.cr.sql_log_count
        module_extra_query_count = odoo.orm.database.sql_db.cursor.sql_counter

        update_operation = (
            'install' if package.state == 'to install' else
            'upgrade' if package.state == 'to upgrade' else
            'reinit' if module_name in registry._reinit_modules else
            None
        ) if update_module else None
        module_log_level = logging.DEBUG
        if update_operation:
            module_log_level = logging.INFO
        _logger.log(module_log_level, 'Loading module %s (%d/%d)', module_name, index, module_count)

        if update_operation:
            if update_operation == 'upgrade' or module_name in registry._force_upgrade_scripts:
                if package.name != 'base':
                    registry._setup_models__(env.cr, [])  # incremental setup
                migrations.migrate_module(package, 'pre')
            if package.name != 'base':
                env.flush_all()

        load_openerp_module(package.name)

        if update_operation == 'install':
            py_module = sys.modules['odoo.addons.%s' % (module_name,)]
            pre_init = package.manifest.get('pre_init_hook')
            if pre_init:
                registry._setup_models__(env.cr, [])  # incremental setup
                getattr(py_module, pre_init)(env)

        model_names = registry.load(package)

        if update_operation:
            model_names = registry.descendants(model_names, '_inherit', '_inherits')
            models_updated |= model_names
            registry._models_to_check -= model_names
            registry._setup_models__(env.cr, [])  # incremental setup
            registry.init_models(env.cr, model_names, {'module': package.name}, update_operation == 'install')
        elif update_module and package.state != 'to remove':
            # The current module has simply been loaded. The models extended by this module
            # and for which we updated the schema, must have their schema checked again.
            # This is because the extension may have changed the model,
            # e.g. adding required=True to an existing field, but the schema has not been
            # updated by this module because it's not marked as 'to upgrade/to install'.
            model_names = registry.descendants(model_names, '_inherit', '_inherits')
            registry._models_to_check |= model_names & models_updated
        elif update_module and package.state == 'to remove':
            # For all model extented (with _inherit) in the package to uninstall, we need to
            # update ir.model / ir.model.fields along side not-null SQL constrains.
            registry._models_to_check |= model_names

        if update_operation:
            # Can't put this line out of the loop: ir.module.module will be
            # registered by init_models() above.
            module = env['ir.module.module'].browse(module_id)
            module._check()

            idref: dict = {}

            if update_operation == 'install':
                load_data(env, idref, 'init', kind='data', package=package)
                if install_demo and package.demo_installable:
                    package.demo = load_demo(env, package, idref, 'init')
            else:  # 'upgrade' or 'reinit'
                # upgrading the module information
                module.write(module.get_values_from_terp(package.manifest))
                mode = 'update' if update_operation == 'upgrade' else 'init'
                load_data(env, idref, mode, kind='data', package=package)
                if package.demo:
                    package.demo = load_demo(env, package, idref, mode)
            env.cr.execute('UPDATE ir_module_module SET demo = %s WHERE id = %s', (package.demo, module_id))
            module.invalidate_model(['demo'])

            migrations.migrate_module(package, 'post')

            # Group reflection can be done only after loading the data
            env['ir.model.fields']._reflect_field_groups(model_names)

            # Update translations for all installed languages
            overwrite = tools.config["overwrite_existing_translations"]
            module._update_translations(overwrite=overwrite)

        if package.name is not None:
            registry._init_modules.add(package.name)

        if update_operation:
            if update_operation == 'install':
                post_init = package.manifest.get('post_init_hook')
                if post_init:
                    getattr(py_module, post_init)(env)
            elif update_operation == 'upgrade':
                # validate the views that have not been checked yet
                env['ir.ui.view']._validate_module_views(module_name)

            registry.updated_modules.append(package.name)

            ver = adapt_version(package.manifest['version'])
            # Set new modules and dependencies
            module.write({'state': 'installed', 'latest_version': ver})

            package.state = 'installed'
            module.env.flush_all()
            module.env.cr.commit()

        test_time = 0.0
        test_queries = 0
        test_results = None

        update_from_config = tools.config['update'] or tools.config['init'] or tools.config['reinit']
        if tools.config['test_enable'] and (update_operation or not update_from_config):
            from odoo.tests import loader  # noqa: PLC0415
            suite = loader.make_suite([module_name], 'at_install')
            if suite.countTestCases():
                if not update_operation:
                    registry._setup_models__(env.cr, [])  # incremental setup
                registry.check_null_constraints(env.cr)
                # Python tests
                tests_t0, tests_q0 = time.time(), odoo.orm.database.sql_db.cursor.sql_counter
                test_results = loader.run_suite(suite, global_report=report)
                assert report is not None, "Missing report during tests"
                report.update(test_results)
                test_time = time.time() - tests_t0
                test_queries = odoo.orm.database.sql_db.cursor.sql_counter - tests_q0

                # tests may have reset the environment
                module = env['ir.module.module'].browse(module_id)


        extra_queries = odoo.orm.database.sql_db.cursor.sql_counter - module_extra_query_count - test_queries
        extras = []
        if test_queries:
            extras.append(f'+{test_queries} test')
        if extra_queries:
            extras.append(f'+{extra_queries} other')
        _logger.log(
            module_log_level, "Module %s loaded in %.2fs%s, %s queries%s",
            module_name, time.time() - module_t0,
            f' (incl. {test_time:.2f}s test)' if test_time else '',
            env.cr.sql_log_count - module_cursor_query_count,
            f' ({", ".join(extras)})' if extras else ''
        )
        if test_results and not test_results.wasSuccessful():
            _logger.error(
                "Module %s: %d failures, %d errors of %d tests",
                module_name, test_results.failures_count, test_results.errors_count,
                test_results.testsRun
            )

    _logger.runbot("%s modules loaded in %.2fs, %s queries (+%s extra)",
                   len(graph),
                   time.time() - t0,
                   env.cr.sql_log_count - loading_cursor_query_count,
                   odoo.orm.database.sql_db.cursor.sql_counter - loading_extra_query_count)  # extra queries: testes, notify, any other closed cursor

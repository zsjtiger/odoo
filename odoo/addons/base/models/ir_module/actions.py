# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The actions on the modules: the state changes, the installation, the uninstallation and the upgrade."""

import psycopg2
import odoo
from odoo import _, modules, tools
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import config
from .helpers import ACTION_DICT

from .module import _logger

def _state_update(self, newstate, states_to_update, level=100):
    if level < 1:
        raise UserError(_('Recursion error in modules dependencies!'))

    for module in self:
        if module.state not in states_to_update:
            continue

        # determine dependency modules to update/others
        update_mods, ready_mods = self.browse(), self.browse()
        for dep in module.dependencies_id:
            if dep.state == 'unknown':
                raise UserError(_(
                    'You try to install module "%(module)s" that depends on module "%(dependency)s".\nBut the latter module is not available in your system.',
                    module=module.name, dependency=dep.name,
                ))
            if dep.depend_id.state == newstate:
                ready_mods += dep.depend_id
            else:
                update_mods += dep.depend_id

        # update dependency modules that require it
        update_mods._state_update(newstate, states_to_update, level=level-1)

        if module.state in states_to_update:
            # check dependencies and update module itself
            self.check_external_dependencies(module.name, newstate)
            module.write({'state': newstate})


def button_install(self):
    company_countries = self.env['res.company'].search([]).country_id
    # domain to select auto-installable (but not yet installed) modules
    auto_domain = [('state', '=', 'uninstalled'), ('auto_install', '=', True)]

    # determine whether an auto-install module must be installed:
    #  - all its dependencies are installed or to be installed,
    #  - at least one dependency is 'to install'
    #  - if the module is country specific, at least one company is in one of the countries
    install_states = frozenset(('installed', 'to install', 'to upgrade'))
    def must_install(module):
        states = {dep.state for dep in module.dependencies_id if dep.auto_install_required}
        return states <= install_states and 'to install' in states and (
            not module.country_ids or module.country_ids & company_countries
        )

    modules = self
    while modules:
        # Mark the given modules and their dependencies to be installed.
        modules._state_update('to install', ['uninstalled'])

        # Determine which auto-installable modules must be installed.

        if config.get('skip_auto_install'):
            modules = None
        else:
            modules = self.search(auto_domain).filtered(must_install)

    # the modules that are installed/to install/to upgrade
    install_mods = self.search([('state', 'in', list(install_states))])

    # check individual exclusions
    install_names = {module.name for module in install_mods}
    for module in install_mods:
        for exclusion in module.exclusion_ids:
            if exclusion.name in install_names:
                raise UserError(_(
                    'Modules "%(module)s" and "%(incompatible_module)s" are incompatible.',
                    module=module.shortdesc,
                    incompatible_module=exclusion.exclusion_id.shortdesc,
                ))

    # check category exclusions
    def closure(module):
        todo = result = module
        while todo:
            result |= todo
            todo = todo.dependencies_id.depend_id
        return result

    exclusives = self.env['ir.module.category'].search([('exclusive', '=', True)])
    for category in exclusives:
        # retrieve installed modules in category and sub-categories
        categories = category.search([('id', 'child_of', category.ids)])
        modules = install_mods.filtered(lambda mod: mod.category_id in categories)
        # the installation is valid if all installed modules in categories
        # belong to the transitive dependencies of one of them
        if modules and not any(modules <= closure(module) for module in modules):
            labels = dict(self.fields_get(['state'])['state']['selection'])
            raise UserError(
                _('You are trying to install incompatible modules in category "%(category)s":%(module_list)s', category=category.name, module_list=''.join(
                    f"\n- {module.shortdesc} ({labels[module.state]})"
                    for module in modules
                ))
            )

    return dict(ACTION_DICT, name=_('Install'))


def button_immediate_install(self):
    """ Installs the selected module(s) immediately and fully,
        returns the next res.config action to execute

        :returns: next res.config item to execute
        :rtype: dict[str, object]
        """
    _logger.info('User #%d triggered module installation', self.env.uid)
    # We use here the request object (which is thread-local) as a kind of
    # "global" env because the env is not usable in the following use case.
    # When installing a Chart of Account, I would like to send the
    # allowed companies to configure it on the correct company.
    # Otherwise, the SUPERUSER won't be aware of that and will try to
    # configure the CoA on his own company, which makes no sense.
    if request:
        request.allowed_company_ids = self.env.companies.ids
    return self._button_immediate_function(self.env.registry[self._name].button_install)


def button_reset_state(self):
    # reset the transient state for all modules in case the module operation is stopped in an unexpected way.
    self.search([('state', '=', 'to install')]).state = 'uninstalled'
    self.search([('state', 'in', ('to upgrade', 'to remove'))]).state = 'installed'
    return True


def check_module_update(self):
    return bool(self.sudo().search_count([('state', 'in', ('to install', 'to upgrade', 'to remove'))], limit=1))


def module_uninstall(self):
    """ Perform the various steps required to uninstall a module completely
        including the deletion of all database structures created by the module:
        tables, columns, constraints, etc.
        """
    modules_to_remove = self.mapped('name')
    self.env['ir.model.data']._module_data_uninstall(modules_to_remove)
    # we deactivate prefetching to not try to read a column that has been deleted
    self.with_context(prefetch_fields=False).write({'state': 'uninstalled', 'latest_version': False})
    return True


def _remove_copied_views(self):
    """ Remove the copies of the views installed by the modules in `self`.

        Those copies do not have an external id so they will not be cleaned by
        `_module_data_uninstall`. This is why we rely on `key` instead.

        It is important to remove these copies because using them will crash if
        they rely on data that don't exist anymore if the module is removed.
        """
    domain = Domain.OR(Domain('key', '=like', m.name + '.%') for m in self)
    orphans = self.env['ir.ui.view'].with_context(active_test=False, force_delete=True).search(domain)
    orphans.unlink()


def next(self):
    """
        Return the action linked to an ir.actions.todo is there exists one that
        should be executed. Otherwise, redirect to /web
        """
    Todos = self.env['ir.actions.todo']
    _logger.info('getting next %s', Todos)
    active_todo = Todos.search([('state', '=', 'open')], limit=1)
    if active_todo:
        _logger.info('next action is "%s"', active_todo.name)
        return active_todo.action_launch()
    return {
        'type': 'ir.actions.act_url',
        'target': 'self',
        'url': '/odoo',
    }


def _button_immediate_function(self, function):
    if not self.env.registry.ready:
        raise UserError(_('The method _button_immediate_install cannot be called on init or non loaded registries. Please use button_install instead.'))

    if modules.module.current_test:
        raise RuntimeError(
            "Module operations inside tests are not transactional and thus forbidden.\n"
            "If you really need to perform module operations to test a specific behavior, it "
            "is best to write it as a standalone script, and ask the runbot/metastorm team "
            "for help."
        )

    self.env.cr.execute("SET LOCAL lock_timeout = '3s'")

    try:
        # raise error if database is updating for module operations
        # acquire the shared-lock for the current transaction only
        self.env.cr.execute("SELECT pg_advisory_xact_lock_shared(hashtext('registry_loading')) NOWAIT")
        # raise error if another transaction is trying to schedule module operations concurrently
        self.env.cr.execute("LOCK ir_module_module IN EXCLUSIVE MODE")
    except psycopg2.OperationalError:
        self.env.cr.rollback()
        raise UserError(_("Odoo is currently processing another module operation.\n"
                           "Please try again later or contact your system administrator."))

    try:
        # This is done because the installation/uninstallation/upgrade can modify a currently
        # running cron job and prevent it from finishing, and since the ir_cron table is locked
        # during execution, the lock won't be released until timeout.
        self.env.cr.execute("SELECT FROM ir_cron FOR UPDATE")
    except psycopg2.OperationalError:
        self.env.cr.rollback()
        raise UserError(_("Odoo is currently processing a scheduled action.\n"
                          "Module operations are not possible at this time, "
                          "please try again later or contact your system administrator."))
    function(self)

    self.env.cr.commit()
    modules.registry.Registry.new(self.env.cr.dbname, update_module=True)
    self.env.cr.rollback()
    assert (self.env.transaction.default_env or self.env).registry is self.env.transaction.registry, "env is bound correctly to the transaction's registry"
    if request:
        assert request.env.transaction is self.env.transaction, "request on another transaction than the model"
        request.registry = request.env.registry

    # pylint: disable=next-method-called
    config = self.env['ir.module.module'].next() or {}
    if config.get('type') not in ('ir.actions.act_window_close',):
        return config

    # reload the client; open the first available root menu
    menu = self.env['ir.ui.menu'].search([('parent_id', '=', False)])[:1]
    return {
        'type': 'ir.actions.client',
        'tag': 'reload',
        'params': {'menu_id': menu.id},
    }


def button_immediate_uninstall(self):
    """
        Uninstall the selected module(s) immediately and fully,
        returns the next res.config action to execute
        """
    _logger.info('User #%d triggered module uninstallation', self.env.uid)
    return self._button_immediate_function(self.env.registry[self._name].button_uninstall)


def button_uninstall(self):
    un_installable_modules = set(self.mapped('name')) & (
        set(tools.config['server_wide_modules']) | set(odoo.modules.loading._FORCED_MODULES)
    )
    if un_installable_modules:
        raise UserError(_("Those modules cannot be uninstalled: %s", ', '.join(un_installable_modules)))
    if any(state not in ('installed', 'to upgrade') for state in self.mapped('state')):
        raise UserError(_(
            "One or more of the selected modules have already been uninstalled, if you "
            "believe this to be an error, you may try again later or contact support."
        ))
    deps = self.downstream_dependencies()
    (self + deps).write({'state': 'to remove'})
    return dict(ACTION_DICT, name=_('Uninstall'))


def button_uninstall_wizard(self):
    """ Launch the wizard to uninstall the given module. """
    return {
        'type': 'ir.actions.act_window',
        'target': 'new',
        'name': _('Uninstall module'),
        'view_mode': 'form',
        'res_model': 'base.module.uninstall',
        'context': {'default_module_ids': self.ids},
    }


def button_immediate_upgrade(self):
    """
        Upgrade the selected module(s) immediately and fully,
        return the next res.config action to execute
        """
    return self._button_immediate_function(self.env.registry[self._name].button_upgrade)


def button_upgrade(self):
    if not self:
        return
    Dependency = self.env['ir.module.module.dependency']
    self.update_list()

    todo = list(self)
    if 'base' in self.mapped('name'):
        # If an installed module is only present in the dependency graph through
        # a new, uninstalled dependency, it will not have been selected yet.
        # An update of 'base' should also update these modules, and as a consequence,
        # install the new dependency.
        todo.extend(self.search([
            ('state', '=', 'installed'),
            ('name', '!=', 'studio_customization'),
            ('id', 'not in', self.ids),
        ]))
    i = 0
    while i < len(todo):
        module = todo[i]
        i += 1
        if module.state not in ('installed', 'to upgrade'):
            raise UserError(_("Cannot upgrade module “%s”. It is not installed.", module.name))
        if self.get_module_info(module.name).get("installable", True):
            self.check_external_dependencies(module.name, 'to upgrade')
        for dep in Dependency.search([('name', '=', module.name)]):
            if (
                dep.module_id.state == 'installed'
                and dep.module_id not in todo
                and dep.module_id.name != 'studio_customization'
            ):
                todo.append(dep.module_id)

    self.browse(module.id for module in todo).write({'state': 'to upgrade'})

    to_install = []
    for module in todo:
        if not self.get_module_info(module.name).get("installable", True):
            continue
        for dep in module.dependencies_id:
            if dep.state == 'unknown':
                raise UserError(_('You try to upgrade the module %(module)s that depends on the module: %(dependency)s.\nBut this module is not available in your system.', module=module.name, dependency=dep.name))
            if dep.state == 'uninstalled':
                to_install += self.search([('name', '=', dep.name)]).ids

    self.browse(to_install).button_install()
    return dict(ACTION_DICT, name=_('Apply Schedule Upgrade'))

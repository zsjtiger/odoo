# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The applications (ir.module.module): the model and the actions on the modules. The methods are split by concern in the other modules of this package."""

import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from .helpers import STATES, assert_log_admin_access


_logger = logging.getLogger('odoo.addons.base.models.ir_module')


class IrModuleModule(models.Model):
    _name = 'ir.module.module'
    _rec_name = "shortdesc"
    _rec_names_search = ('name', 'shortdesc', 'summary')
    _description = "Module"
    _order = 'application desc,sequence,name'
    _allow_sudo_commands = False
    _clear_cache_name = 'stable'      # cache to clear on create/write/update
    _clear_cache_on_fields = ('name', 'state')
    @classmethod
    def get_module_info(cls, name):
        return _info.get_module_info(cls, name)
    @api.depends('name', 'description')
    def _get_desc(self):
        return _info._get_desc(self)
    @api.depends('name')
    def _get_latest_version(self):
        return _info._get_latest_version(self)
    @api.depends('name', 'state')
    def _get_views(self):
        return _info._get_views(self)
    @api.depends('icon')
    def _get_icon_image(self):
        return _info._get_icon_image(self)
    name = fields.Char('Technical Name', readonly=True, required=True)
    category_id = fields.Many2one('ir.module.category', string='Category', readonly=True, index=True)
    shortdesc = fields.Char('Module Name', readonly=True, translate=True)
    summary = fields.Char('Summary', readonly=True, translate=True)
    description = fields.Text('Description', readonly=True, translate=True)
    description_html = fields.Html('Description HTML', compute='_get_desc')
    author = fields.Char("Author", readonly=True)
    maintainer = fields.Char('Maintainer', readonly=True)
    contributors = fields.Text('Contributors', readonly=True)
    website = fields.Char("Website", readonly=True)
    installed_version = fields.Char('Latest Version', compute='_get_latest_version')
    latest_version = fields.Char('Installed Version', readonly=True)
    published_version = fields.Char('Published Version', readonly=True)
    url = fields.Char('URL', readonly=True)
    sequence = fields.Integer('Sequence', default=100)
    dependencies_id = fields.One2many('ir.module.module.dependency', 'module_id',
                                       string='Dependencies', readonly=True)
    country_ids = fields.Many2many('res.country', 'module_country', 'module_id', 'country_id')
    exclusion_ids = fields.One2many('ir.module.module.exclusion', 'module_id',
                                    string='Exclusions', readonly=True)
    auto_install = fields.Boolean('Automatic Installation',
                                   help='An auto-installable module is automatically installed by the '
                                        'system when all its dependencies are satisfied. '
                                        'If the module has no dependency, it is always installed.')
    state = fields.Selection(STATES, string='Status', default='uninstallable', readonly=True, index=True)
    demo = fields.Boolean('Demo Data', default=False, readonly=True)
    test_data = fields.Boolean('Test Data', default=False, readonly=True)
    license = fields.Selection([
        ('GPL-2', 'GPL Version 2'),
        ('GPL-2 or any later version', 'GPL-2 or later version'),
        ('GPL-3', 'GPL Version 3'),
        ('GPL-3 or any later version', 'GPL-3 or later version'),
        ('AGPL-3', 'Affero GPL-3'),
        ('LGPL-3', 'LGPL Version 3'),
        ('Other OSI approved licence', 'Other OSI Approved License'),
        ('OEEL-1', 'Odoo Enterprise Edition License v1.0'),
        ('OPL-1', 'Odoo Proprietary License v1.0'),
        ('Other proprietary', 'Other Proprietary')
    ], string='License', default='LGPL-3', readonly=True)
    menus_by_module = fields.Text(string='Menus', compute='_get_views', store=True)
    reports_by_module = fields.Text(string='Reports', compute='_get_views', store=True)
    views_by_module = fields.Text(string='Views', compute='_get_views', store=True)
    application = fields.Boolean('Application', readonly=True)
    icon = fields.Char('Icon URL')
    icon_image = fields.Binary(string='Icon', compute='_get_icon_image')
    icon_flag = fields.Char(string='Flag', compute='_get_icon_image')
    to_buy = fields.Boolean('Odoo Enterprise Module', default=False)
    iap_paid_service = fields.Boolean("Contains In-App Purchases")
    _name_uniq = models.Constraint(
        'UNIQUE (name)',
        "The name of the module must be unique!",
    )
    @api.ondelete(at_uninstall=False)
    def _unlink_except_installed(self):
        for module in self:
            if module.state in ('installed', 'to upgrade', 'to remove', 'to install'):
                raise UserError(_('You are trying to remove a module that is installed or will be installed.'))
    def _get_modules_to_load_domain(self):
        return _graph._get_modules_to_load_domain(self)
    def check_external_dependencies(self, module_name, newstate='to install'):
        return _graph.check_external_dependencies(self, module_name, newstate)
    def _state_update(self, newstate, states_to_update, level=100):
        return _actions._state_update(self, newstate, states_to_update, level)
    @assert_log_admin_access
    def button_install(self):
        return _actions.button_install(self)
    @assert_log_admin_access
    def button_immediate_install(self):
        return _actions.button_immediate_install(self)
    @assert_log_admin_access
    @api.model
    def button_reset_state(self):
        return _actions.button_reset_state(self)
    @api.model
    def check_module_update(self):
        return _actions.check_module_update(self)
    @assert_log_admin_access
    def module_uninstall(self):
        return _actions.module_uninstall(self)
    def _remove_copied_views(self):
        return _actions._remove_copied_views(self)
    def downstream_dependencies(self, known_deps=None, exclude_states=('uninstalled', 'uninstallable', 'to remove')):
        return _graph.downstream_dependencies(self, known_deps, exclude_states)
    def upstream_dependencies(self, known_deps=None, exclude_states=('installed', 'uninstallable', 'to remove')):
        return _graph.upstream_dependencies(self, known_deps, exclude_states)
    def next(self):
        return _actions.next(self)
    def _button_immediate_function(self, function):
        return _actions._button_immediate_function(self, function)
    @assert_log_admin_access
    def button_immediate_uninstall(self):
        return _actions.button_immediate_uninstall(self)
    @assert_log_admin_access
    def button_uninstall(self):
        return _actions.button_uninstall(self)
    @assert_log_admin_access
    def button_uninstall_wizard(self):
        return _actions.button_uninstall_wizard(self)
    @assert_log_admin_access
    def button_immediate_upgrade(self):
        return _actions.button_immediate_upgrade(self)
    @assert_log_admin_access
    def button_upgrade(self):
        return _actions.button_upgrade(self)
    @staticmethod
    def get_values_from_terp(terp):
        return _update.get_values_from_terp(terp)
    @api.model_create_multi
    def create(self, vals_list):
        return _update.create(self, vals_list)
    @assert_log_admin_access
    @api.model
    def update_list(self):
        return _update.update_list(self)
    def _update_from_terp(self, terp):
        return _update._update_from_terp(self, terp)
    def _update_dependencies(self, depends=None, auto_install_requirements=()):
        return _update._update_dependencies(self, depends, auto_install_requirements)
    def _update_countries(self, countries=()):
        return _update._update_countries(self, countries)
    def _update_exclusions(self, excludes=None):
        return _update._update_exclusions(self, excludes)
    def _update_category(self, category='Uncategorized'):
        return _update._update_category(self, category)
    def _update_translations(self, filter_lang=None, overwrite=False):
        return _update._update_translations(self, filter_lang, overwrite)
    def _check(self):
        return _lookup._check(self)
    def _get(self, name):
        return _lookup._get(self, name)
    @api.ormcache('name', cache='stable')
    def _get_id(self, name):
        return _lookup._get_id(self, name)
    @api.model
    @api.ormcache(cache='stable')
    def _installed(self):
        return _lookup._installed(self)
    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        return _lookup.search_panel_select_range(self, field_name, **kwargs)
    @api.model
    def _load_module_terms(self, modules, langs, overwrite=False):
        return _translations._load_module_terms(self, modules, langs, overwrite)
    @api.model
    def _load_non_installed_modules_manifest_terms(self, langs):
        return _translations._load_non_installed_modules_manifest_terms(self, langs)
    @api.model
    def _extract_resource_attachment_translations(self, module, lang):
        return _translations._extract_resource_attachment_translations(self, module, lang)


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import info as _info, graph as _graph, actions as _actions, update as _update, lookup as _lookup, translations as _translations  # noqa: E402

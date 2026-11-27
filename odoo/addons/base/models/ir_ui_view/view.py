"""The views (ir.ui.view): their fields and their constraints. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools.misc import ConstantMapping
from odoo.tools.text.translate import xml_translate


class IrUiView(models.Model):
    _name = 'ir.ui.view'
    _description = 'View'
    _order = "priority,name,id"
    _allow_sudo_commands = False
    _clear_cache_name = 'templates'
    name = fields.Char(string='View Name', required=True, copy=True)
    model = fields.Char(index=True)
    key = fields.Char(index='btree_not_null')
    priority = fields.Integer(string='Sequence', default=16, required=True)
    type = fields.Selection([('list', 'List'),
                             ('form', 'Form'),
                             ('graph', 'Graph'),
                             ('pivot', 'Pivot'),
                             ('calendar', 'Calendar'),
                             ('kanban', 'Kanban'),
                             ('search', 'Search'),
                             ('card', "Card"),
                             ('qweb', 'QWeb')], string='View Type')
    arch = fields.Text(compute='_compute_arch', inverse='_inverse_arch', string='View Architecture',
                       help="""This field should be used when accessing view arch. It will use translation.
                               Note that it will read `arch_db` or `arch_fs` if in dev-xml mode.""")
    arch_base = fields.Text(compute='_compute_arch_base', inverse='_inverse_arch_base', string='Base View Architecture',
                            help="This field is the same as `arch` field without translations")
    arch_db = fields.Text(string='Arch Blob', translate=xml_translate,
                          help="This field stores the view arch.")
    arch_fs = fields.Char(string='Arch Filename', help="""File from where the view originates.
                                                          Useful to (hard) reset broken views or to read arch from file in dev-xml mode.""")
    arch_updated = fields.Boolean(string='Modified Architecture')
    arch_prev = fields.Text(string='Previous View Architecture', help="""This field will save the current `arch_db` before writing on it.
                                                                         Useful to (soft) reset a broken view.""")
    inherit_id = fields.Many2one('ir.ui.view', string='Inherited View', ondelete='restrict', index=True)
    inherit_children_ids = fields.One2many('ir.ui.view', 'inherit_id', string='Views which inherit from this one')
    model_data_id = fields.Many2one('ir.model.data', string="Model Data",
                                    compute='_compute_model_data_id', search='_search_model_data_id')
    xml_id = fields.Char(string="External ID", compute='_compute_xml_id',
                         help="ID of the view defined in xml file")
    group_ids = fields.Many2many('res.groups', 'ir_ui_view_group_rel', 'view_id', 'group_id',
                                 string='Groups', help="If this field is empty, the view applies to all users. Otherwise, the view applies to the users of those groups only.")
    mode = fields.Selection([('primary', "Base view"), ('extension', "Extension View")],
                            string="View inheritance mode", default='primary', required=True,
                            help="""Only applies if this view inherits from an other one (inherit_id is not False/Null).

* if extension (default), if this view is requested the closest primary view
is looked up (via inherit_id), then all views inheriting from it with this
view's model are applied
* if primary, the closest primary view is fully resolved (even if it uses a
different model than this one), then this view's inheritance specs
(<xpath/>) are applied, and the result is used as if it were this view's
actual arch.
""")
    warning_info = fields.Html(string="Warning information", compute='_compute_warning_info')
    notes = fields.Html(string="Notes")
    active = fields.Boolean(default=True,
                            help="""If this view is inherited,
* if True, the view always extends its parent
* if False, the view currently does not extend its parent but can be enabled
         """)
    model_id = fields.Many2one("ir.model", string="Model of the view", compute='_compute_model_id', inverse='_inverse_compute_model_id',
                               write_sequence=-10)  # inverse before 'arch', whose inverse validates the view against 'model'
    invalid_locators = fields.Json(compute='_compute_invalid_locators')
    technical_usage = fields.Selection(selection=[], string="Technical Usage")
    @api.depends('arch_db', 'arch_fs', 'arch_updated')
    @api.depends_context('read_arch_from_file', 'lang', 'edit_translations', 'check_translations')
    def _compute_arch(self):
        return _view_compute._compute_arch(self)
    def _inverse_arch(self):
        return _view_compute._inverse_arch(self)
    @api.depends('arch')
    @api.depends_context('read_arch_from_file')
    def _compute_arch_base(self):
        return _view_compute._compute_arch_base(self)
    def _inverse_arch_base(self):
        return _view_compute._inverse_arch_base(self)
    def reset_arch(self, mode='soft'):
        return _view_compute.reset_arch(self, mode)
    @api.depends('write_date')
    def _compute_model_data_id(self):
        return _view_compute._compute_model_data_id(self)
    def _search_model_data_id(self, operator, value):
        return _view_compute._search_model_data_id(self, operator, value)
    @api.depends('model')
    def _compute_model_id(self):
        return _view_compute._compute_model_id(self)
    def _inverse_compute_model_id(self):
        return _view_compute._inverse_compute_model_id(self)
    @api.depends('arch', 'inherit_id')
    def _compute_invalid_locators(self):
        return _view_compute._compute_invalid_locators(self)
    def _compute_xml_id(self):
        return _view_compute._compute_xml_id(self)
    def _valid_inheritance(self, arch):
        return _view_validate_attrs._valid_inheritance(self, arch)
    def _check_xml(self):
        return _view_validate_attrs._check_xml(self)
    @api.constrains('group_ids', 'inherit_id', 'mode')
    def _check_groups(self):
        return _view_validate_attrs._check_groups(self)
    @api.constrains('inherit_id')
    def _check_000_inheritance(self):
        return _view_validate_attrs._check_000_inheritance(self)
    _inheritance_mode = models.Constraint(
        "CHECK (mode != 'extension' OR inherit_id IS NOT NULL)",
        "Invalid inheritance mode: if the mode is 'extension', the view must extend an other view",
    )
    _qweb_required_key = models.Constraint(
        "CHECK (type != 'qweb' OR key IS NOT NULL)",
        "Invalid key: QWeb view should have a key",
    )
    _model_type_inherit_id = models.Index('(model, inherit_id)')
    def _compute_defaults(self, values):
        return _view_compute._compute_defaults(self, values)
    @api.depends('arch')
    def _compute_warning_info(self):
        return _view_compute._compute_warning_info(self)
    def _validate_xml_encoding(self, text):
        return _view_validate_attrs._validate_xml_encoding(self, text)
    @api.model_create_multi
    def create(self, vals_list):
        return _view_crud.create(self, vals_list)
    def write(self, vals):
        return _view_crud.write(self, vals)
    def unlink(self):
        return _view_crud.unlink(self)
    def _update_field_translations(self, field_name, translations, digest=None, source_lang=''):
        return _view_crud._update_field_translations(self, field_name, translations, digest, source_lang)
    def copy_data(self, default=None):
        return _view_crud.copy_data(self, default)
    @api.model
    def default_view(self, model, view_type):
        return _view_inheritance.default_view(self, model, view_type)
    @api.model
    def _get_default_view_domain(self, model, view_type):
        return _view_inheritance._get_default_view_domain(self, model, view_type)
    @api.model
    def _get_inheriting_views_domain(self):
        return _view_inheritance._get_inheriting_views_domain(self)
    @api.model
    def _get_filter_xmlid_query(self, *, modules):
        return _view_inheritance._get_filter_xmlid_query(self, modules=modules)
    def _get_inheriting_views(self):
        return _view_inheritance._get_inheriting_views(self)
    def _filter_loaded_views(self, check_view_ids):
        return _view_inheritance._filter_loaded_views(self, check_view_ids)
    def _check_view_access(self):
        return _view_inheritance._check_view_access(self)
    def _raise_view_error(self, message, node=None, *, from_exception=None, from_traceback=None):
        return _view_inheritance._raise_view_error(self, message, node, from_exception=from_exception, from_traceback=from_traceback)
    def _log_view_warning(self, message, node):
        return _view_inheritance._log_view_warning(self, message, node)
    def locate_node(self, arch, spec):
        return _view_inheritance.locate_node(self, arch, spec)
    def inherit_branding(self, specs_tree):
        return _view_inheritance.inherit_branding(self, specs_tree)
    def _add_validation_flag(self, combined_arch, view=None, arch=None):
        return _view_inheritance._add_validation_flag(self, combined_arch, view, arch)
    @api.model
    def apply_inheritance_specs(self, source, specs_tree, pre_locate=None):
        return _view_inheritance.apply_inheritance_specs(self, source, specs_tree, pre_locate)
    def _combine(self, hierarchy: dict):
        return _view_inheritance._combine(self, hierarchy)
    def get_combined_arch(self):
        return _view_inheritance.get_combined_arch(self)
    def _get_combined_arch(self):
        return _view_inheritance._get_combined_arch(self)
    def _get_combined_archs(self):
        return _view_inheritance._get_combined_archs(self)
    def _get_view_refs(self, node):
        return _view_inheritance._get_view_refs(self, node)
    @api.model
    def _get_cached_template_prefetched_keys(self):
        return _view_templates._get_cached_template_prefetched_keys(self)
    def _get_template_minimal_cache_keys(self):
        return _view_templates._get_template_minimal_cache_keys(self)
    @api.model
    @api.ormcache('id_or_xmlid', 'isinstance(id_or_xmlid, str) and self._get_template_minimal_cache_keys()', cache='templates')
    def _get_cached_template_info(self, id_or_xmlid: int | str, *, _view: models.BaseModel | None=None):
        return _view_templates._get_cached_template_info(self, id_or_xmlid, _view=_view)
    @api.model
    def _get_template_view(self, id_or_xmlid: int | str, raise_if_not_found=True) -> models.BaseModel:
        return _view_templates._get_template_view(self, id_or_xmlid, raise_if_not_found)
    @api.model
    def _get_template_domain(self, xmlids: list[str]) -> Domain:
        return _view_templates._get_template_domain(self, xmlids)
    @api.model
    def _get_template_order(self) -> str:
        return _view_templates._get_template_order(self)
    @api.model
    def _fetch_template_views(self, ids_or_xmlids: Sequence[int | str]) -> dict[int | str, models.BaseModel | Exception]:
        return _view_templates._fetch_template_views(self, ids_or_xmlids)
    @api.ormcache(cache='templates')
    def _clear_preload_views_cache_if_needed(self):
        return _view_templates._clear_preload_views_cache_if_needed(self)
    def _preload_views(self, refs: Sequence[int | str]) -> dict[int | str, dict]:
        return _view_templates._preload_views(self, refs)
    def postprocess_and_fields(self, node, model=None, **options):
        return _view_postprocess.postprocess_and_fields(self, node, model, **options)
    def _postprocess_access_rights(self, tree):
        return _view_postprocess._postprocess_access_rights(self, tree)
    def _postprocess_debug_to_cache(self, tree):
        return _view_postprocess._postprocess_debug_to_cache(self, tree)
    def _postprocess_debug(self, tree):
        return _view_postprocess._postprocess_debug(self, tree)
    def _postprocess_view(self, node, model_name, editable=True, node_info=None, **options):
        return _view_postprocess._postprocess_view(self, node, model_name, editable, node_info, **options)
    def _get_access_groups(self, group_definitions, model_name):
        return _view_postprocess._get_access_groups(self, group_definitions, model_name)
    def _add_missing_fields(self, node, name_manager):
        return _view_postprocess._add_missing_fields(self, node, name_manager)
    def _postprocess_on_change(self, arch, model):
        return _view_postprocess._postprocess_on_change(self, arch, model)
    def _get_x2many_missing_view_archs(self, field, field_node, node_info):
        return _view_postprocess._get_x2many_missing_view_archs(self, field, field_node, node_info)
    def _postprocess_attributes(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_attributes(self, node, name_manager, node_info)
    def _postprocess_tag_calendar(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_calendar(self, node, name_manager, node_info)
    def _postprocess_tag_field(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_field(self, node, name_manager, node_info)
    def _postprocess_tag_form(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_form(self, node, name_manager, node_info)
    def _postprocess_tag_groupby(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_groupby(self, node, name_manager, node_info)
    def _postprocess_tag_card(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_card(self, node, name_manager, node_info)
    def _postprocess_tag_label(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_label(self, node, name_manager, node_info)
    def _postprocess_tag_filter(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_filter(self, node, name_manager, node_info)
    def _postprocess_tag_search(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_search(self, node, name_manager, node_info)
    def _postprocess_tag_kanban(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_kanban(self, node, name_manager, node_info)
    def _postprocess_tag_list(self, node, name_manager, node_info):
        return _view_postprocess._postprocess_tag_list(self, node, name_manager, node_info)
    def _editable_node(self, node, name_manager):
        return _view_postprocess._editable_node(self, node, name_manager)
    def _editable_tag_form(self, node, name_manager):
        return _view_postprocess._editable_tag_form(self, node, name_manager)
    def _editable_tag_list(self, node, name_manager):
        return _view_postprocess._editable_tag_list(self, node, name_manager)
    def _editable_tag_field(self, node, name_manager):
        return _view_postprocess._editable_tag_field(self, node, name_manager)
    def _onchange_able_view(self, node):
        return _view_postprocess._onchange_able_view(self, node)
    def _onchange_able_view_form(self, node):
        return _view_postprocess._onchange_able_view_form(self, node)
    def _onchange_able_view_list(self, node):
        return _view_postprocess._onchange_able_view_list(self, node)
    def _onchange_able_view_kanban(self, node):
        return _view_postprocess._onchange_able_view_kanban(self, node)
    def _modifiers_from_model(self, node):
        return _view_postprocess._modifiers_from_model(self, node)
    def _validate_view(self, node, model_name, view_type=None, editable=True, node_info=None):
        return _view_validate_tags._validate_view(self, node, model_name, view_type, editable, node_info)
    def _validate_tag_form(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_form(self, node, name_manager, node_info)
    def _validate_tag_list(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_list(self, node, name_manager, node_info)
    def _validate_tag_graph(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_graph(self, node, name_manager, node_info)
    def _validate_tag_calendar(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_calendar(self, node, name_manager, node_info)
    def _validate_tag_search(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_search(self, node, name_manager, node_info)
    def _validate_tag_field(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_field(self, node, name_manager, node_info)
    def _validate_tag_filter(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_filter(self, node, name_manager, node_info)
    def _validate_tag_button(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_button(self, node, name_manager, node_info)
    def _validate_tag_groupby(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_groupby(self, node, name_manager, node_info)
    def _validate_tag_searchpanel(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_searchpanel(self, node, name_manager, node_info)
    def _validate_tag_label(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_label(self, node, name_manager, node_info)
    def _validate_tag_page(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_page(self, node, name_manager, node_info)
    def _validate_tag_img(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_img(self, node, name_manager, node_info)
    def _validate_tag_a(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_a(self, node, name_manager, node_info)
    def _validate_tag_ul(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_ul(self, node, name_manager, node_info)
    def _validate_tag_div(self, node, name_manager, node_info):
        return _view_validate_tags._validate_tag_div(self, node, name_manager, node_info)
    def _check_dropdown_menu(self, node):
        return _view_validate_tags._check_dropdown_menu(self, node)
    def _check_progress_bar(self, node):
        return _view_validate_tags._check_progress_bar(self, node)
    def _is_qweb_based_view(self, view_type):
        return _view_validate_tags._is_qweb_based_view(self, view_type)
    def _validate_attributes(self, node, name_manager, node_info):
        return _view_validate_attrs._validate_attributes(self, node, name_manager, node_info)
    def _validate_classes(self, node, expr):
        return _view_validate_attrs._validate_classes(self, node, expr)
    def _validate_data_icon_accessibility(self, node, description):
        return _view_validate_attrs._validate_data_icon_accessibility(self, node, description)
    def _validate_qweb_directive(self, node, directive, view_type):
        return _view_validate_attrs._validate_qweb_directive(self, node, directive, view_type)
    def _validate_expression(self, node, name_manager, py_expression, use, node_info):
        return _view_validate_attrs._validate_expression(self, node, name_manager, py_expression, use, node_info)
    def _validate_domain_identifiers(self, node, name_manager, domain, use, target_model, node_info):
        return _view_validate_attrs._validate_domain_identifiers(self, node, name_manager, domain, use, target_model, node_info)
    def _check_field_paths(self, node, field_paths, model_name, use):
        return _view_validate_attrs._check_field_paths(self, node, field_paths, model_name, use)
    def _read_template_keys(self):
        return _view_templates._read_template_keys(self)
    def _get_view_etrees(self):
        return _view_templates._get_view_etrees(self)
    def _contains_branded(self, node):
        return _view_branding._contains_branded(self, node)
    def _pop_view_branding(self, element):
        return _view_branding._pop_view_branding(self, element)
    def distribute_branding(self, e, branding=None, parent_xpath='', index_map=ConstantMapping(1)):
        return _view_branding.distribute_branding(self, e, branding, parent_xpath, index_map)
    def is_node_branded(self, node):
        return _view_branding.is_node_branded(self, node)
    @api.readonly
    @api.model
    def render_public_asset(self, template, values=None):
        return _view_branding.render_public_asset(self, template, values)
    def _render_template(self, template, values=None):
        return _view_templates._render_template(self, template, values)
    @api.model
    def _validate_custom_views(self, model):
        return _view_validate_attrs._validate_custom_views(self, model)
    @api.model
    def _validate_module_views(self, module):
        return _view_validate_attrs._validate_module_views(self, module)
    def _create_all_specific_views(self, processed_modules):
        return _view_crud._create_all_specific_views(self, processed_modules)
    def _get_specific_views(self):
        return _view_crud._get_specific_views(self)
    def _load_records_write(self, values):
        return _view_crud._load_records_write(self, values)
    def _load_records_write_on_cow(self, cow_view, inherit_id, values):
        return _view_crud._load_records_write_on_cow(self, cow_view, inherit_id, values)


_logger = logging.getLogger('odoo.addons.base.models.ir_ui_view')


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import view_compute as _view_compute, view_validate_tags as _view_validate_tags, view_validate_attrs as _view_validate_attrs, view_crud as _view_crud, view_inheritance as _view_inheritance, view_templates as _view_templates, view_postprocess as _view_postprocess, view_branding as _view_branding  # noqa: E402

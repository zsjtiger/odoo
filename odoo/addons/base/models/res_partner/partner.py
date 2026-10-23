# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The partners (res.partner): the model, its fields and its constraints. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import logging
import re
import typing
from odoo import api, fields, models

if typing.TYPE_CHECKING:
    from ..res_users import ResUsers
    from ..res_partner_bank import ResPartnerBank
    from ..res_country import ResCountry, ResCountryState
    from ..res_company import ResCompany


_logger = logging.getLogger('odoo.addons.base.models.res_partner')

from .category import ResPartnerCategory
from .helpers import _lang_get, _tzs
from .industry import ResPartnerIndustry


class ResPartner(models.Model):
    _name = 'res.partner'
    _description = 'Contact'
    _explanation = "Foundational model for all people and companies (customers, vendors, employees, etc.). Used for identifying individuals or organizations."
    _inherit = ['format.address.mixin', 'format.vat.label.mixin', 'avatar.mixin', 'properties.base.definition.mixin']
    _order = "complete_name ASC, id DESC"
    _rec_names_search = ('complete_name', 'email', 'ref', 'vat')  # TODO vat must be sanitized the same way for storing/searching
    _allow_sudo_commands = False
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of
    _complete_name_displayed_types = ('invoice', 'delivery', 'other')
    def _default_category(self):
        return _records._default_category(self)
    @api.model
    def default_get(self, fields):
        return _records.default_get(self, fields)
    name = fields.Char(index=True, default_export_compatible=True)
    complete_name = fields.Char(compute='_compute_complete_name', store=True, index=True)
    parent_id: ResPartner = fields.Many2one('res.partner', string='Related Company', index=True)
    parent_name = fields.Char(related='parent_id.name', readonly=True, store=False, string='Parent name')
    child_ids: ResPartner = fields.One2many('res.partner', 'parent_id', string='Related Contacts', domain=[('active', '=', True)], context={'active_test': False})
    ref = fields.Char(string='Reference', index=True)
    lang = fields.Selection(_lang_get, string='Language',
                            compute='_compute_lang', readonly=False, store=True,
                            help="All the emails and documents sent to this contact will be translated in this language.")
    active_lang_count = fields.Integer(compute='_compute_active_lang_count')
    tz = fields.Selection(_tzs, string='Timezone', default=lambda self: self.env.context.get('tz'),
                          help="When printing documents and exporting/importing data, time values are computed according to this timezone.\n"
                               "If the timezone is not set, UTC (Coordinated Universal Time) is used.\n"
                               "Anywhere else, time values are computed according to the time offset of your web client.")
    tz_offset = fields.Char(compute='_compute_tz_offset', string='Timezone offset')
    user_id: ResUsers = fields.Many2one(
        'res.users', string='Salesperson',
        compute='_compute_user_id',
        precompute=True,  # avoid queries post-create
        readonly=False, store=True,
        help='The internal user in charge of this contact.')
    vat = fields.Char(string='Tax ID', index='btree_not_null', inverse='_inverse_vat', help="You can use '/' to indicate that the customer has no Tax ID.")
    has_vat = fields.Boolean(
        string="Has Tax ID",
        compute="_compute_has_vat",
        compute_sql="_compute_sql_has_vat",
        compute_sudo=True,
        help="Technical field indicating whether the Tax ID is not a placeholder."
             "Returns False for placeholder values such as '/', 'NA', 'na', or an empty string.",
    )
    additional_identifiers = fields.Json(string="Additional Identifiers", copy=False)
    available_additional_identifiers_metadata = fields.Json(compute='_compute_available_additional_identifiers_metadata')
    vat_label = fields.Char(string='Tax ID Label', compute='_compute_vat_label')
    same_vat_partner_id: ResPartner = fields.Many2one('res.partner', string='Partner with same Tax ID', compute='_compute_same_vat_partner_id', store=False)
    bank_ids: ResPartnerBank = fields.One2many('res.partner.bank', 'partner_id', string='Banks')
    website = fields.Char('Website Link')
    comment = fields.Html(string='Notes')
    category_id: ResPartnerCategory = fields.Many2many('res.partner.category', column1='partner_id',
                                    column2='category_id', string='Tags', default=_default_category)
    active = fields.Boolean(default=True)
    employee = fields.Boolean(help="Check this box if this contact is an Employee.")
    function = fields.Char(string='Job Position')
    type = fields.Selection(
        [('contact', 'Contact'),
         ('invoice', 'Invoice'),
         ('delivery', 'Delivery'),
         ('other', 'Other'),
        ], string='Address Type',
        default='contact')
    type_address_label = fields.Char('Address Type Description', compute='_compute_type_address_label')
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char(change_default=True)
    city = fields.Char()
    state_id: ResCountryState = fields.Many2one("res.country.state", string='State', ondelete='restrict', index='btree_not_null', domain="[('country_id', '=?', country_id)]")
    country_id: ResCountry = fields.Many2one('res.country', string='Country', ondelete='restrict', index='btree_not_null', inverse='_inverse_vat')
    country_code = fields.Char(related='country_id.code', string="Country Code")
    partner_latitude = fields.Float(string='Latitude', digits=(10, 7))
    partner_longitude = fields.Float(string='Longitude', digits=(10, 7))
    email = fields.Char()
    email_formatted = fields.Char(
        'Formatted Email', compute='_compute_email_formatted',
        help='Format email address "Name <email@domain>"')
    phone = fields.Char()
    is_company = fields.Boolean(string='Is a Company', default=False, compute="_compute_is_company", store=True,
        help="Check if the contact is a company, otherwise it is a person")
    is_public = fields.Boolean(compute='_compute_is_public', compute_sudo=True)
    industry_id: ResPartnerIndustry = fields.Many2one('res.partner.industry', 'Industry')
    company_id: ResCompany = fields.Many2one('res.company', 'Company', index=True)
    color = fields.Integer(string='Color Index', default=0)
    user_ids: ResUsers = fields.One2many('res.users', 'partner_id', string='Users', bypass_search_access=True)
    main_user_id: ResUsers = fields.Many2one(
        "res.users",
        string="Main User",
        compute="_compute_main_user_id",
        help="There can be several users related to the same partner. "
        "When a single user is needed, this field attempts to find the most appropriate one.",
    )
    partner_share = fields.Boolean(
        'Share Partner', compute='_compute_partner_share', store=True,
        help="Either customer (not a user), either shared user. Indicated the current partner is a customer without "
             "access or with a limited access created for sharing data.")
    contact_address = fields.Char(compute='_compute_address', string="Complete Address")
    address = fields.Char(compute='_compute_address', string="Address (without name)")
    contact_address_inline = fields.Char(compute='_compute_address', string="Complete Address inline")
    address_inline = fields.Char(compute='_compute_address', string="Address inline (without name)")
    commercial_partner_id: ResPartner = fields.Many2one(
        'res.partner', string='Commercial Entity',
        compute='_compute_commercial_partner', store=True,
        recursive=True, index=True)
    commercial_company_name = fields.Char('Company Name Entity', related='commercial_partner_id.name',
                                          store=True)
    barcode = fields.Char(help="Use a barcode to identify this contact.", copy=False, company_dependent=True)
    self: ResPartner = fields.Many2one(comodel_name='res.partner', compute='_compute_get_ids')
    application_statistics = fields.Json(string="Stats", compute="_compute_application_statistics")
    @property
    def country_name(self):
        return _addresses.country_name(self)
    def _compute_application_statistics(self):
        return _partner_fields._compute_application_statistics(self)
    def _compute_application_statistics_hook(self):
        return _partner_fields._compute_application_statistics_hook(self)
    _check_name = models.Constraint(
        "CHECK( (type='contact' AND name IS NOT NULL) or (type!='contact') )",
        "Contacts require a name",
    )
    def _get_street_split(self):
        return _addresses._get_street_split(self)
    @api.depends('name', 'user_ids.share', 'image_1920', 'is_company', 'type')
    def _compute_avatar_1920(self):
        return _avatars._compute_avatar_1920(self)
    @api.depends('name', 'user_ids.share', 'image_1024', 'is_company', 'type')
    def _compute_avatar_1024(self):
        return _avatars._compute_avatar_1024(self)
    @api.depends('name', 'user_ids.share', 'image_512', 'is_company', 'type')
    def _compute_avatar_512(self):
        return _avatars._compute_avatar_512(self)
    @api.depends('name', 'user_ids.share', 'image_256', 'is_company', 'type')
    def _compute_avatar_256(self):
        return _avatars._compute_avatar_256(self)
    @api.depends('name', 'user_ids.share', 'image_128', 'is_company', 'type')
    def _compute_avatar_128(self):
        return _avatars._compute_avatar_128(self)
    def _compute_avatar(self, avatar_field, image_field):
        return _avatars._compute_avatar(self, avatar_field, image_field)
    def _avatar_get_placeholder_path(self):
        return _avatars._avatar_get_placeholder_path(self)
    def _get_complete_name(self):
        return _partner_fields._get_complete_name(self)
    @api.depends('is_company', 'name', 'parent_id.name', 'type', 'commercial_company_name')
    def _compute_complete_name(self):
        return _partner_fields._compute_complete_name(self)
    @api.depends('parent_id')
    def _compute_lang(self):
        return _partner_fields._compute_lang(self)
    @api.depends('lang')
    def _compute_active_lang_count(self):
        return _partner_fields._compute_active_lang_count(self)
    @api.depends('tz')
    def _compute_tz_offset(self):
        return _partner_fields._compute_tz_offset(self)
    @api.depends('parent_id')
    def _compute_user_id(self):
        return _partner_fields._compute_user_id(self)
    @api.depends_context('uid')
    @api.depends('user_ids.active', 'user_ids.share')
    def _compute_main_user_id(self):
        return _partner_fields._compute_main_user_id(self)
    @api.depends('user_ids.share', 'user_ids.active')
    def _compute_partner_share(self):
        return _partner_fields._compute_partner_share(self)
    @api.depends('vat', 'company_id', 'country_id')
    def _compute_same_vat_partner_id(self):
        return _vat._compute_same_vat_partner_id(self)
    @api.depends_context('company')
    def _compute_vat_label(self):
        return _vat._compute_vat_label(self)
    @api.depends('parent_id', 'type')
    def _compute_type_address_label(self):
        return _addresses._compute_type_address_label(self)
    @api.depends_context('lang')
    @api.depends(lambda self: self._display_address_depends())
    def _compute_address(self):
        return _addresses._compute_address(self)
    def _compute_get_ids(self):
        return _partner_fields._compute_get_ids(self)
    @api.depends('parent_id.commercial_partner_id', 'parent_id')
    def _compute_commercial_partner(self):
        return _partner_fields._compute_commercial_partner(self)
    @api.constrains('parent_id')
    def _check_parent_id(self):
        return _partner_fields._check_parent_id(self)
    @api.constrains('company_id')
    def _check_partner_company(self):
        return _partner_fields._check_partner_company(self)
    @api.onchange('parent_id')
    def onchange_parent_id(self):
        return _partner_fields.onchange_parent_id(self)
    @api.onchange('country_id')
    def _onchange_country_id(self):
        return _partner_fields._onchange_country_id(self)
    @api.onchange('state_id')
    def _onchange_state(self):
        return _partner_fields._onchange_state(self)
    @api.onchange('parent_id', 'company_id')
    def _onchange_company_id(self):
        return _partner_fields._onchange_company_id(self)
    @api.depends('name', 'email')
    def _compute_email_formatted(self):
        return _partner_fields._compute_email_formatted(self)
    @api.constrains('barcode')
    def _check_barcode_unicity(self):
        return _partner_fields._check_barcode_unicity(self)
    def _convert_fields_to_values(self, field_names):
        return _addresses._convert_fields_to_values(self, field_names)
    @api.model
    def _address_fields(self):
        return _addresses._address_fields(self)
    @api.model
    def _formatting_address_fields(self):
        return _addresses._formatting_address_fields(self)
    def _get_address_values(self):
        return _addresses._get_address_values(self)
    def _update_address(self, vals):
        return _addresses._update_address(self, vals)
    @api.model
    def _commercial_fields(self):
        return _commercial._commercial_fields(self)
    @api.model
    def _synced_commercial_fields(self):
        return _commercial._synced_commercial_fields(self)
    def _get_commercial_values(self):
        return _commercial._get_commercial_values(self)
    def _get_synced_commercial_values(self):
        return _commercial._get_synced_commercial_values(self)
    def _apply_synced_identifiers(self, source_identifiers):
        return _commercial._apply_synced_identifiers(self, source_identifiers)
    def _write_commercial_sync(self, sync_vals):
        return _commercial._write_commercial_sync(self, sync_vals)
    @api.model
    def _company_dependent_commercial_fields(self):
        return _commercial._company_dependent_commercial_fields(self)
    def _commercial_sync_from_company(self):
        return _commercial._commercial_sync_from_company(self)
    def _company_dependent_commercial_sync(self):
        return _commercial._company_dependent_commercial_sync(self)
    def _commercial_sync_to_descendants(self, fields_to_sync=None):
        return _commercial._commercial_sync_to_descendants(self, fields_to_sync)
    def _fields_sync(self, values):
        return _commercial._fields_sync(self, values)
    def _children_sync(self, values):
        return _commercial._children_sync(self, values)
    def _handle_first_contact_creation(self):
        return _commercial._handle_first_contact_creation(self)
    def _clean_website(self, website):
        return _partner_fields._clean_website(self, website)
    @api.depends('vat')
    def _compute_has_vat(self):
        return _partner_fields._compute_has_vat(self)
    def _compute_sql_has_vat(self, table):
        return _partner_fields._compute_sql_has_vat(self, table)
    @api.depends('has_vat', 'commercial_partner_id')
    def _compute_is_company(self):
        return _partner_fields._compute_is_company(self)
    def _compute_is_public(self):
        return _partner_fields._compute_is_public(self)
    def write(self, vals):
        return _records.write(self, vals)
    @api.model_create_multi
    def create(self, vals_list):
        return _records.create(self, vals_list)
    @api.ondelete(at_uninstall=False)
    def _unlink_except_user(self):
        return _records._unlink_except_user(self)
    def _load_records_create(self, vals_list):
        return _records._load_records_create(self, vals_list)
    def _create_parent_from_name(self, parent_name, additional_values=None):
        return _commercial._create_parent_from_name(self, parent_name, additional_values)
    def _create_contact_parent_company(self, values):
        return _commercial._create_contact_parent_company(self, values)
    def open_commercial_entity(self):
        return _commercial.open_commercial_entity(self)
    @api.depends('complete_name', 'email', 'vat', 'additional_identifiers', 'state_id', 'country_id')
    @api.depends_context('show_address', 'partner_show_db_id', 'show_email', 'show_identifier', 'lang', 'formatted_display_name')
    def _compute_display_name(self):
        return _partner_fields._compute_display_name(self)
    @api.model
    def name_create(self, name):
        return _records.name_create(self, name)
    @api.model
    def find_or_create(self, email, assert_valid_email=False):
        return _records.find_or_create(self, email, assert_valid_email)
    def address_get(self, adr_pref=None):
        return _addresses.address_get(self, adr_pref)
    @api.model
    def view_header_get(self, view_id, view_type):
        return _addresses.view_header_get(self, view_id, view_type)
    @api.model
    def _get_default_address_format(self):
        return _addresses._get_default_address_format(self)
    def _get_address_format(self):
        return _addresses._get_address_format(self)
    def _prepare_display_address(self, without_name=False):
        return _addresses._prepare_display_address(self, without_name)
    def _display_address(self, without_name=False, separator='\n'):
        return _addresses._display_address(self, without_name, separator)
    def _display_address_depends(self):
        return _addresses._display_address_depends(self)
    @api.model
    def get_import_templates(self):
        return _records.get_import_templates(self)
    @api.model
    def _check_import_consistency(self, vals_list):
        return _records._check_import_consistency(self, vals_list)
    def _get_all_addr(self):
        return _addresses._get_all_addr(self)
    @api.model
    def _get_res_city_by_name(self, name, country_id):
        return _addresses._get_res_city_by_name(self, name, country_id)
    @api.constrains('additional_identifiers')
    def _check_additional_identifiers(self):
        return _identifiers._check_additional_identifiers(self)
    @api.onchange('vat', 'country_id')
    def _onchange_vat(self):
        return _vat._onchange_vat(self)
    def _inverse_vat(self):
        return _vat._inverse_vat(self)
    def _check_vat(self, validation='error'):
        return _vat._check_vat(self, validation)
    @api.model
    def _run_vat_checks(self, country, vat, partner_name='', validation='error'):
        return _vat._run_vat_checks(self, country, vat, partner_name, validation)
    @api.model
    def _check_vat_number(self, country_code, vat_number):
        return _vat._check_vat_number(self, country_code, vat_number)
    @api.model
    def _build_vat_error_message(self, country_code, wrong_vat, record_label):
        return _vat._build_vat_error_message(self, country_code, wrong_vat, record_label)
    @api.model
    def _get_country_specific_vat_variants(self, normalized_vat, country_prefix):
        return _vat._get_country_specific_vat_variants(self, normalized_vat, country_prefix)
    @api.model
    def _format_vat_number(self, country_code, vat):
        return _vat._format_vat_number(self, country_code, vat)
    @api.model
    def _validate_identifier(self, key, value, validation=False):
        return _identifiers._validate_identifier(self, key, value, validation)
    @api.model
    def _validate_identifier_by_scheme(self, scheme, value, validation=False):
        return _identifiers._validate_identifier_by_scheme(self, scheme, value, validation)
    @api.model
    def _format_identifier(self, identifier_type, value):
        return _identifiers._format_identifier(self, identifier_type, value)
    @api.model
    def _pick_preferred_identifier(self, identifiers, filter_func=None, sort_key=None):
        return _identifiers._pick_preferred_identifier(self, identifiers, filter_func, sort_key)
    @api.depends_context('company')
    @api.depends('country_id', 'additional_identifiers')
    def _compute_available_additional_identifiers_metadata(self):
        return _identifiers._compute_available_additional_identifiers_metadata(self)
    def _lazy_translate_additional_identifiers_metadata(self, metadata):
        return _identifiers._lazy_translate_additional_identifiers_metadata(self, metadata)
    def _get_additional_identifier(self, identifier_type):
        return _identifiers._get_additional_identifier(self, identifier_type)
    def _set_additional_identifier(self, identifier_type, value):
        return _identifiers._set_additional_identifier(self, identifier_type, value)
    def _get_all_identifiers(self, enrich=False):
        return _identifiers._get_all_identifiers(self, enrich)
    @api.model
    def _get_all_identifiers_metadata(self):
        return _identifiers._get_all_identifiers_metadata(self)
    @api.model
    def _get_allowed_identifier_metadata_keys(self):
        return _identifiers._get_allowed_identifier_metadata_keys(self)
    @api.model
    def _get_all_identifiers_metadata_by_scheme(self):
        return _identifiers._get_all_identifiers_metadata_by_scheme(self)
    @api.model
    def _get_all_additional_identifiers_metadata(self):
        return _identifiers._get_all_additional_identifiers_metadata(self)
    @api.model
    def _get_legal_entity_category_priority(self):
        return _identifiers._get_legal_entity_category_priority(self)
    @api.model
    def _get_tax_category_priority(self):
        return _identifiers._get_tax_category_priority(self)
    @api.model
    def _get_identifier_label(self, identifier_key):
        return _identifiers._get_identifier_label(self, identifier_key)
    @api.model
    def _is_individual_identifier(self, identifier_key):
        return _identifiers._is_individual_identifier(self, identifier_key)
    @api.model
    def _is_company_identifier(self, identifier_key):
        return _identifiers._is_company_identifier(self, identifier_key)
    def _is_geolocalized(self):
        return _identifiers._is_geolocalized(self)
    def _get_preferred_legal_entity_identifier_vals(self):
        return _identifiers._get_preferred_legal_entity_identifier_vals(self)
    def _get_preferred_tax_identifier_vals(self):
        return _identifiers._get_preferred_tax_identifier_vals(self)
    def _deduce_additional_identifiers_from_vat(self):
        return _identifiers._deduce_additional_identifiers_from_vat(self)
    def _clean_additional_identifiers(self, vals):
        return _identifiers._clean_additional_identifiers(self, vals)
    def _deduce_country_code(self):
        return _identifiers._deduce_country_code(self)
    @api.model
    def _get_identifier_fields(self):
        return _identifiers._get_identifier_fields(self)
    @api.model
    def _convert_hu_local_to_eu_vat(self, local_vat):
        return _vat._convert_hu_local_to_eu_vat(self, local_vat)
    def _ie_check_char(self, vat):
        return _vat._ie_check_char(self, vat)
    _check_vat_al_re = re.compile(r'^[JKLM][0-9]{8}[A-Z]$')
    def check_vat_al(self, vat):
        return _vat.check_vat_al(self, vat)
    __check_vat_br_re = re.compile(r'^[\dA-Z]+$')
    def check_vat_br(self, vat):
        return _vat.check_vat_br(self, vat)
    _check_vat_ch_re = re.compile(r'E([0-9]{9}|-[0-9]{3}\.[0-9]{3}\.[0-9]{3})( )?(MWST|TVA|IVA)$')
    def check_vat_ch(self, vat):
        return _vat.check_vat_ch(self, vat)
    _check_vat_cr_re = re.compile(r'^(?:[1-9]\d{8}|\d{10}|[1-9]\d{10,11})$')
    def check_vat_cr(self, vat):
        return _vat.check_vat_cr(self, vat)
    def check_vat_de(self, vat):
        return _vat.check_vat_de(self, vat)
    def check_vat_do(self, vat):
        return _vat.check_vat_do(self, vat)
    def check_vat_ec(self, vat):
        return _vat.check_vat_ec(self, vat)
    def check_vat_gr(self, vat):
        return _vat.check_vat_gr(self, vat)
    __check_vat_gt_testing_infile = re.compile(r'98[0-9]{10}K')
    def check_vat_gt(self, vat):
        return _vat.check_vat_gt(self, vat)
    _check_tin_hu_individual_re = re.compile(r'^8\d{9}$')
    _check_tin_hu_companies_re = re.compile(r'^\d{8}-?[1-5]-?\d{2}$')
    _check_tin_hu_european_re = re.compile(r'^\d{8}$')
    def check_vat_hu(self, vat):
        return _vat.check_vat_hu(self, vat)
    def check_vat_id(self, vat):
        return _vat.check_vat_id(self, vat)
    def check_vat_ie(self, vat):
        return _vat.check_vat_ie(self, vat)
    def check_vat_il(self, vat):
        return _vat.check_vat_il(self, vat)
    def check_vat_in(self, vat):
        return _vat.check_vat_in(self, vat)
    def check_vat_jp(self, vat):
        return _vat.check_vat_jp(self, vat)
    def check_vat_ma(self, vat):
        return _vat.check_vat_ma(self, vat)
    _check_vat_mx_re = re.compile(r"(?P<primeras>[A-Za-z\xd1\xf1&]{3,4})"
                                   r"[ \-_]?"
                                   r"(?P<ano>[0-9]{2})(?P<mes>[01][0-9])(?P<dia>[0-3][0-9])"
                                   r"[ \-_]?"
                                   r"(?P<code>[A-Za-z0-9&\xd1\xf1]{3})")
    def check_vat_mx(self, vat):
        return _vat.check_vat_mx(self, vat)
    def check_vat_no(self, vat):
        return _vat.check_vat_no(self, vat)
    def check_vat_pe(self, vat):
        return _vat.check_vat_pe(self, vat)
    _check_vat_ph_re = re.compile(r"\d{3}-\d{3}-\d{3}(-\d{3,5})?$")
    def check_vat_ph(self, vat):
        return _vat.check_vat_ph(self, vat)
    def check_vat_pk(self, vat):
        return _vat.check_vat_pk(self, vat)
    _check_tin1_ro_natural_persons = re.compile(r'[1-9]\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{6}')
    _check_tin2_ro_natural_persons = re.compile(r'9000\d{9}')
    def check_vat_ro(self, vat):
        return _vat.check_vat_ro(self, vat)
    def check_vat_rs(self, vat):
        return _vat.check_vat_rs(self, vat)
    _check_vat_sa_re = re.compile(r"^3[0-9]{13}3$")
    def check_vat_sa(self, vat):
        return _vat.check_vat_sa(self, vat)
    def check_vat_th(self, vat):
        return _vat.check_vat_th(self, vat)
    def check_vat_tr(self, vat):
        return _vat.check_vat_tr(self, vat)
    def check_vat_tw(self, vat):
        return _vat.check_vat_tw(self, vat)
    def check_vat_ua(self, vat):
        return _vat.check_vat_ua(self, vat)
    def check_vat_uy(self, vat):
        return _vat.check_vat_uy(self, vat)
    def check_vat_uz(self, vat):
        return _vat.check_vat_uz(self, vat)
    def check_vat_ve(self, vat):
        return _vat.check_vat_ve(self, vat)
    __check_vat_vn_re = re.compile(r'^\d{10}(?:-?\d{3})?$|^\d{12}$')
    __check_vat_vn_companies_re = re.compile(r'^\d{10}(?:-?\d{3})?$')
    def check_vat_vn(self, vat):
        return _vat.check_vat_vn(self, vat)
    def format_vat_al(self, vat):
        return _vat.format_vat_al(self, vat)
    def format_vat_ca(self, vat):
        return _vat.format_vat_ca(self, vat)
    def format_vat_ch(self, vat):
        return _vat.format_vat_ch(self, vat)
    def format_vat_cl(self, vat):
        return _vat.format_vat_cl(self, vat)
    def format_vat_co(self, vat):
        return _vat.format_vat_co(self, vat)
    def format_vat_eu(self, vat):
        return _vat.format_vat_eu(self, vat)
    def format_vat_hu(self, vat):
        return _vat.format_vat_hu(self, vat)
    def format_vat_is(self, vat):
        return _vat.format_vat_is(self, vat)
    def format_vat_pk(self, vat):
        return _vat.format_vat_pk(self, vat)
    def format_vat_sm(self, vat):
        return _vat.format_vat_sm(self, vat)
    def format_vat_vn(self, vat):
        return _vat.format_vat_vn(self, vat)
    def is_valid_ruc_ec(self, vat):
        return _vat.is_valid_ruc_ec(self, vat)


ResPartner._update_address.__override__ = False  # whitelist super()


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import partner_fields as _partner_fields, avatars as _avatars, addresses as _addresses, commercial as _commercial, vat as _vat, identifiers as _identifiers, records as _records  # noqa: E402

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The fields of the models (ir.model.fields): the model and its fields. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import logging
from odoo import api, fields, models


_logger = logging.getLogger('odoo.addons.base.models.ir_model')
FIELD_TYPES = [(key, key) for key in sorted(fields.Field._by_type__)]
FIELD_INDEX_TYPES = [
    ('btree', 'B-tree'),
    ('btree_not_null', 'B-tree, excluding nulls'),
    ('trigram', 'Trigram'),
]


class IrModelFields(models.Model):
    _name = 'ir.model.fields'
    _description = "Field"
    _order = "name, id"
    _rec_name = 'field_description'
    _allow_sudo_commands = False
    name = fields.Char(string='Field Name', default='x_', required=True, index=True)
    model = fields.Char(string='Model Name', required=True, index=True,
                        help="The technical name of the model this field belongs to")
    relation = fields.Char(string='Related Model',
                           help="For relationship fields, the technical name of the target model")
    relation_field = fields.Char(help="For one2many fields, the field on the target model that implements the opposite many2one relationship")
    relation_model_field = fields.Char(
        help="For many2one_reference fields, the field that stores the technical name of the target model")
    relation_field_id = fields.Many2one('ir.model.fields', compute='_compute_relation_field_id',
                                        store=True, ondelete='cascade', string='Relation field')
    model_id = fields.Many2one('ir.model', string='Model', required=True, index=True, ondelete='cascade',
                               help="The model this field belongs to")
    field_description = fields.Char(string='Field Label', default='', required=True, translate=True)
    help = fields.Text(string='Field Help', translate=True)
    ttype = fields.Selection(selection=FIELD_TYPES, string='Field Type', required=True)
    selection = fields.Char(string="Selection Options (Deprecated)",
                            compute='_compute_selection', inverse='_inverse_selection')
    selection_ids = fields.One2many("ir.model.fields.selection", "field_id",
                                    string="Selection Options", copy=True)
    copied = fields.Boolean(string='Copied',
                            compute='_compute_copied', store=True, readonly=False,
                            help="Whether the value is copied when duplicating a record.")
    related = fields.Char(string='Related Field Definition', help="The corresponding related field, if any. This must be a dot-separated list of field names.")
    related_field_id = fields.Many2one('ir.model.fields', compute='_compute_related_field_id',
                                       store=True, string="Related Field", ondelete='cascade')
    required = fields.Boolean()
    readonly = fields.Boolean()
    index = fields.Selection(
        FIELD_INDEX_TYPES,
        string='Index',
        help="The kind of database index requested for this field. "
             "B-tree indexes support equality and range searches; excluding nulls makes the index smaller "
             "when most values are empty; trigram indexes speed up text pattern searches. "
             "Leaving this empty does not remove an index that already exists.",
    )
    allowed_index_types = fields.Json(compute='_compute_allowed_index_types')
    translate = fields.Selection([
        ('standard', 'Translate as a whole'),
        ('html_translate', 'Translate HTML terms'),
        ('xml_translate', 'Translate XML terms'),
    ], string='Translatable', help="Whether values for this field can be translated (enables the translation mechanism for that field)")
    company_dependent = fields.Boolean(string='Company Dependent', help="Whether values for this field is company dependent", readonly=True)
    size = fields.Integer()
    state = fields.Selection([('manual', 'Custom Field'), ('base', 'Base Field')], string='Type', default='manual', required=True, readonly=True, index=True)
    on_delete = fields.Selection([('cascade', 'Cascade'), ('set null', 'Set NULL'), ('restrict', 'Restrict')],
                                 string='On Delete', default='set null', help='On delete property for many2one fields')
    domain = fields.Char(default="[]", help="The optional domain to restrict possible values for relationship fields, "
                                            "specified as a Python expression defining a list of triplets. "
                                            "For example: [('color','=','red')]")
    depends_on = fields.Char(
        string="Depends on",
        help="Name of a field of the same model. The candidate values of this many2one field "
             "are filtered by the value of that field, through the domain. "
             "For example: [('country_id', '=', country_id)] if country_id else []",
    )
    groups = fields.Many2many('res.groups', 'ir_model_fields_group_rel', 'field_id', 'group_id')
    group_expand = fields.Boolean(string="Expand Groups",
                                  help="If checked, all the records of the target model will be included\n"
                                        "in a grouped result (e.g. 'Group By' filters, Kanban columns, etc.).\n"
                                        "Note that it can significantly reduce performance if the target model\n"
                                        "of the field contains a lot of records; usually used on models with\n"
                                        "few records (e.g. Stages, Job Positions, Event Types, etc.).")
    selectable = fields.Boolean(default=True)
    modules = fields.Char(compute='_in_modules', string='In Apps', help='List of modules in which the field is defined')
    relation_table = fields.Char(help="Used for custom many2many fields to define a custom relation table name")
    column1 = fields.Char(string='Column 1', help="Column referring to the record in the model table")
    column2 = fields.Char(string="Column 2", help="Column referring to the record in the comodel table")
    compute = fields.Text(help="Code to compute the value of the field.\n"
                               "Iterate on the recordset 'self' and assign the field's value:\n\n"
                               "    for record in self:\n"
                               "        record['size'] = len(record.name)\n\n"
                               "Modules time, datetime, dateutil are available.")
    depends = fields.Char(string='Dependencies', help="Dependencies of compute method; "
                                                      "a list of comma-separated field names, like\n\n"
                                                      "    name, partner_id.name")
    store = fields.Boolean(string='Stored', default=True, help="Whether the value is stored in the database.")
    currency_field = fields.Char(string="Currency field", help="Name of the Many2one field holding the res.currency")
    sanitize = fields.Boolean(string='Sanitize HTML', default=True)
    sanitize_overridable = fields.Boolean(string='Sanitize HTML overridable', default=False)
    sanitize_tags = fields.Boolean(string='Sanitize HTML Tags', default=True)
    sanitize_attributes = fields.Boolean(string='Sanitize HTML Attributes', default=True)
    sanitize_style = fields.Boolean(string='Sanitize HTML Style', default=False)
    sanitize_form = fields.Boolean(string='Sanitize HTML Form', default=True)
    strip_style = fields.Boolean(string='Strip Style Attribute', default=False)
    strip_classes = fields.Boolean(string='Strip Class Attribute', default=False)
    @api.depends('relation', 'relation_field')
    def _compute_relation_field_id(self):
        return _computed._compute_relation_field_id(self)
    @api.depends('related')
    def _compute_related_field_id(self):
        return _computed._compute_related_field_id(self)
    @api.depends('selection_ids')
    def _compute_selection(self):
        return _computed._compute_selection(self)
    def _inverse_selection(self):
        return _computed._inverse_selection(self)
    @api.depends('ttype', 'related', 'compute')
    def _compute_copied(self):
        return _computed._compute_copied(self)
    def _get_allowed_index_types(self):
        return _computed._get_allowed_index_types(self)
    @api.depends('state', 'ttype', 'store', 'translate', 'company_dependent')
    def _compute_allowed_index_types(self):
        return _computed._compute_allowed_index_types(self)
    @api.onchange('store', 'ttype', 'translate', 'company_dependent')
    def _onchange_index(self):
        return _computed._onchange_index(self)
    @api.constrains('index', 'state', 'ttype', 'store', 'translate', 'company_dependent')
    def _check_index(self):
        return _checks._check_index(self)
    @api.depends()
    def _in_modules(self):
        return _computed._in_modules(self)
    @api.constrains('domain')
    def _check_domain(self):
        return _checks._check_domain(self)

    @api.constrains('depends_on', 'ttype', 'model')
    def _check_depends_on(self):
        return _checks._check_depends_on(self)

    @api.constrains('name')
    def _check_name(self):
        return _checks._check_name(self)
    _name_unique = models.Constraint('UNIQUE(model, name)', "Field names must be unique per model.")
    _size_gt_zero = models.Constraint('CHECK (size>=0)', 'Size of the field cannot be negative.')
    _name_manual_field = models.Constraint(
        "CHECK (state != 'manual' OR name LIKE 'x\\_%')",
        "Custom fields must have a name that starts with 'x_'!",
    )
    def _related_field(self):
        return _checks._related_field(self)
    @api.constrains('related')
    def _check_related(self):
        return _checks._check_related(self)
    @api.onchange('related')
    def _onchange_related(self):
        return _computed._onchange_related(self)
    @api.onchange('relation')
    def _onchange_relation(self):
        return _computed._onchange_relation(self)
    @api.constrains('relation')
    def _check_relation(self):
        return _checks._check_relation(self)
    @api.constrains('depends')
    def _check_depends(self):
        return _checks._check_depends(self)
    @api.onchange('compute')
    def _onchange_compute(self):
        return _computed._onchange_compute(self)
    @api.constrains('relation_table')
    def _check_relation_table(self):
        return _checks._check_relation_table(self)
    @api.constrains('relation', 'relation_field')
    def _check_relation_field(self):
        return _checks._check_relation_field(self)
    @api.constrains('currency_field')
    def _check_currency_field(self):
        return _checks._check_currency_field(self)
    @api.model
    def _custom_many2many_names(self, model_name, comodel_name):
        return _computed._custom_many2many_names(self, model_name, comodel_name)
    @api.onchange('ttype', 'model_id', 'relation')
    def _onchange_ttype(self):
        return _computed._onchange_ttype(self)
    @api.onchange('relation_table')
    def _onchange_relation_table(self):
        return _computed._onchange_relation_table(self)
    @api.constrains('required', 'ttype', 'on_delete')
    def _check_on_delete_required_m2o(self):
        return _checks._check_on_delete_required_m2o(self)
    def _get(self, model_name, name):
        return _records._get(self, model_name, name)
    @api.ormcache('model_name', cache='stable')
    def _get_ids(self, model_name):
        return _records._get_ids(self, model_name)
    def _drop_column(self):
        return _records._drop_column(self)
    def _prepare_update(self):
        return _records._prepare_update(self)
    def unlink(self):
        return _records.unlink(self)
    @api.model_create_multi
    def create(self, vals_list):
        return _records.create(self, vals_list)
    def _get_writable_properties(self):
        return _records._get_writable_properties(self)
    def write(self, vals):
        return _records.write(self, vals)
    @api.depends('field_description', 'model')
    def _compute_display_name(self):
        return _computed._compute_display_name(self)
    def _reflect_field_params(self, field, model_id):
        return _manual._reflect_field_params(self, field, model_id)
    def _reflect_fields(self, model_names):
        return _manual._reflect_fields(self, model_names)
    def _reflect_field_groups(self, model_names):
        return _manual._reflect_field_groups(self, model_names)
    @api.ormcache(cache='stable')
    def _all_manual_field_data(self):
        return _manual._all_manual_field_data(self)
    def _get_manual_field_data(self, model_name):
        return _manual._get_manual_field_data(self, model_name)
    def _instanciate_attrs(self, field_data):
        return _manual._instanciate_attrs(self, field_data)
    @api.model
    def _is_manual_name(self, name):
        return _manual._is_manual_name(self, name)
    @api.model
    def get_field_string(self, model_name):
        return _manual.get_field_string(self, model_name)
    @api.model
    def get_field_help(self, model_name):
        return _manual.get_field_help(self, model_name)
    @api.model
    def get_field_selection(self, model_name, field_name):
        return _manual.get_field_selection(self, model_name, field_name)
    @api.model
    @api.ormcache('model_name', 'self.env.lang', cache='stable')
    def _get_fields_cached(self, model_name):
        return _manual._get_fields_cached(self, model_name)


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import checks as _checks, computed as _computed, records as _records, manual as _manual  # noqa: E402

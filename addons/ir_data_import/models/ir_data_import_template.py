# -*- coding: utf-8 -*-
import base64
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..xlsx_io import build_template

COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
RESERVED_COLUMNS = ('action', 'id', 'record_type', 'validation_error')
NOT_IMPORTABLE_TYPES = ('one2many', 'many2many', 'binary', 'properties', 'reference')
SKIP_AUTO = ('id', 'display_name', '__last_update', 'create_uid', 'create_date', 'write_uid', 'write_date')

DEFAULT_STYLE = {
    'header_font_color': '#FFFFFF',
    'header_fill_color': '#0E7C86',
    'header_bold': True,
    'header_height': 24,
    'freeze_header': True,
    'show_gridlines': True,
    'action_fill_color': '#FFF2CC',
    'required_fill_color': '#C0392B',
    'show_help_sheet': True,
    'help_sheet_name': 'Help',
}


def _selection_options(env, field):
    return [str(label) for _value, label in field._description_selection(env)]


def auto_columns(env, Model):
    """Columns used when no template is configured: every readable, stored, plain field."""
    if not Model.has_access('read'):
        return []
    columns = []
    for name, field in Model._fields.items():
        if name in SKIP_AUTO or name in RESERVED_COLUMNS:
            continue
        if field.type in NOT_IMPORTABLE_TYPES or not field.store or field.readonly:
            continue
        header = field.string or name
        options = _selection_options(env, field) if field.type == 'selection' else None
        if field.type == 'boolean':
            options = [_('Yes'), _('No')]
        columns.append({
            'name': name, 'header': header, 'required': False,
            'width': max(14, len(header) * 2), 'align': 'right' if field.type in ('integer', 'float', 'monetary') else 'left',
            'number_format': None, 'options': options, 'hidden': False,
            'note': field.help or '', 'example': None,
        })
    return columns


class IrDataImportTemplate(models.Model):
    _name = 'ir.data.import.template'
    _description = 'Data Import Template'
    _order = 'model_id, record_type_id, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    model_name = fields.Char(related='model_id.model', readonly=True)
    record_type_id = fields.Many2one(
        'ir.record.type', string='Record Type', ondelete='cascade',
        domain="[('model_id', '=', model_id)]",
        help='Empty: the general template of the model.',
    )
    version = fields.Integer(default=1, readonly=True)
    match_by = fields.Selection([
        ('name', 'Name'), ('xmlid', 'External ID'),
    ], string='Many2one matching', default='name', required=True)
    include_example = fields.Boolean(string='Example row', default=False)
    column_ids = fields.One2many('ir.data.import.template.column', 'template_id', string='Columns', copy=True)

    # Excel style
    sheet_name = fields.Char(string='Sheet name')
    header_font_color = fields.Char(default='#FFFFFF')
    header_fill_color = fields.Char(default='#0E7C86')
    header_bold = fields.Boolean(default=True)
    header_height = fields.Integer(default=24)
    freeze_header = fields.Boolean(default=True)
    show_gridlines = fields.Boolean(default=True)
    action_fill_color = fields.Char(default='#FFF2CC')
    required_fill_color = fields.Char(default='#C0392B')
    show_help_sheet = fields.Boolean(default=True)
    help_sheet_name = fields.Char(default='Help')

    @api.constrains('header_font_color', 'header_fill_color', 'action_fill_color', 'required_fill_color')
    def _check_colors(self):
        for record in self:
            for field_name in ('header_font_color', 'header_fill_color', 'action_fill_color', 'required_fill_color'):
                value = record[field_name]
                if value and not COLOR_RE.match(value):
                    raise ValidationError(_('%(field)s must be a colour like #0E7C86.', field=field_name))

    @api.constrains('model_id', 'record_type_id', 'active')
    def _check_one_active_template(self):
        for record in self.filtered('active'):
            duplicate = self.search_count([
                ('id', '!=', record.id), ('active', '=', True),
                ('model_id', '=', record.model_id.id),
                ('record_type_id', '=', record.record_type_id.id or False),
            ])
            if duplicate:
                raise ValidationError(_('Only one active template per model and record type.'))

    @api.constrains('record_type_id', 'model_id')
    def _check_record_type_model(self):
        for record in self.filtered('record_type_id'):
            if record.record_type_id.model_id != record.model_id:
                raise ValidationError(_('The record type must belong to the template model.'))

    def _bump_version(self):
        for record in self:
            super(IrDataImportTemplate, record).write({'version': record.version + 1})

    def write(self, vals):
        res = super().write(vals)
        if vals.keys() & {'match_by', 'include_example', 'sheet_name', 'model_id', 'record_type_id'}:
            self._bump_version()
        return res

    @api.model
    def _find_template(self, model_name, record_type=None):
        """The active template for a model and record type; the general one as fallback."""
        # search by model id: a path such as model_id.model needs read access on ir.model
        model = self.env['ir.model'].sudo()._get(model_name)
        base = [('model_id', '=', model.id), ('active', '=', True)]
        template = self.search(base + [('record_type_id', '=', record_type.id if record_type else False)], limit=1)
        if not template and record_type:
            template = self.search(base + [('record_type_id', '=', False)], limit=1)
        return template

    def _style(self):
        self.ensure_one()
        style = dict(DEFAULT_STYLE)
        style.update({
            'sheet_name': self.sheet_name or self.model_name,
            'header_font_color': self.header_font_color,
            'header_fill_color': self.header_fill_color,
            'header_bold': self.header_bold,
            'header_height': self.header_height,
            'freeze_header': self.freeze_header,
            'show_gridlines': self.show_gridlines,
            'action_fill_color': self.action_fill_color,
            'required_fill_color': self.required_fill_color,
            'show_help_sheet': self.show_help_sheet,
            'help_sheet_name': self.help_sheet_name,
        })
        return style

    def _column_specs(self):
        self.ensure_one()
        specs = []
        for column in self.column_ids:
            field = column.field_id
            if not field:
                continue
            options = None
            if column.dropdown:
                if field.ttype == 'selection':
                    options = _selection_options(self.env, self.env[self.model_name]._fields[field.name])
                elif field.ttype == 'boolean':
                    options = [_('Yes'), _('No')]
            specs.append({
                'name': field.name, 'header': column.header or field.field_description or field.name,
                'required': column.required_on_create, 'width': column.column_width or None,
                'align': column.align, 'number_format': column.number_format, 'options': options,
                'hidden': column.hidden, 'note': column.help or '', 'example': column.example,
            })
        return specs

    @api.model
    def _build_xlsx(self, model_name, record_type=None):
        """Return (bytes, filename) of the download template for a model (and record type)."""
        Model = self.env[model_name]
        template = self._find_template(model_name, record_type)
        if template:
            style = template._style()
            fields_columns = template._column_specs()
            example = {}
            if template.include_example:
                example = {c['name']: c['example'] for c in fields_columns}
        else:
            style = dict(DEFAULT_STYLE, sheet_name=model_name)
            fields_columns = auto_columns(self.env, Model)
            example = {}
        has_types = 'record_type_id' in Model._fields
        columns = [
            {'name': 'action', 'header': _('Action (N/U/D)'), 'required': False, 'width': 10, 'align': 'center',
             'options': ['N', 'U', 'D'], 'note': _('N = new, U = update, D = delete')},
            {'name': 'id', 'header': _('ID'), 'required': False, 'width': 12, 'align': 'right', 'options': None,
             'note': _('Database ID or external ID (module.xmlid). Required for U and D, empty for N.')},
        ]
        if has_types:
            columns.append({'name': 'record_type', 'header': _('Record Type'), 'required': False, 'width': 16,
                            'align': 'left', 'options': None,
                            'note': _('Code or name of the record type. Empty: default type.')})
        columns += fields_columns
        help_rows = [(_('Column'), _('Technical name'), _('Required'), _('Help'))]
        for column in columns:
            help_rows.append((column['header'], column['name'], 'yes' if column.get('required') else '',
                              column.get('note') or ''))
        content = build_template(columns, style, example=example, help_rows=help_rows)
        return content, f'{model_name}_template.xlsx'

    @api.model
    def _download_general(self, model_name):
        """Download action for the general template of a model (used by the import dialog)."""
        content, filename = self._build_xlsx(model_name)
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'datas': base64.b64encode(content),
            'res_model': 'ir.data.import.wizard', 'res_id': 0,
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}

    def action_download_xlsx(self):
        self.ensure_one()
        content, filename = self._build_xlsx(self.model_name)
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'datas': base64.b64encode(content),
            'res_model': self._name, 'res_id': self.id,
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}


class IrDataImportTemplateColumn(models.Model):
    _name = 'ir.data.import.template.column'
    _description = 'Data Import Template Column'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one('ir.data.import.template', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one('ir.model.fields', string='Field', required=True, ondelete='cascade')
    header = fields.Char(compute='_compute_header', store=True, readonly=False)
    required_on_create = fields.Boolean(string='Required for new records')
    example = fields.Char()
    help = fields.Char(string='Help text')
    column_width = fields.Integer(string='Width')
    number_format = fields.Char(string='Number format', help='For example 0.00 or yyyy-mm-dd')
    align = fields.Selection([('left', 'Left'), ('center', 'Center'), ('right', 'Right')], default='left')
    dropdown = fields.Boolean(string='Dropdown', help='Selection and boolean fields: offer the options in Excel.')
    hidden = fields.Boolean()

    _template_field_unique = models.Constraint(
        'UNIQUE(template_id, field_id)', 'A field can appear only once in a template.',
    )

    @api.depends('field_id')
    def _compute_header(self):
        for column in self:
            column.header = column.field_id.field_description if column.field_id else False

    @api.constrains('field_id', 'template_id')
    def _check_field_model(self):
        for column in self:
            if column.field_id.model != column.template_id.model_name:
                raise ValidationError(_('The field must belong to the template model.'))
            if column.field_id.name in RESERVED_COLUMNS:
                raise ValidationError(_('%s is a reserved column name.', column.field_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.template_id._bump_version()
        return records

    def write(self, vals):
        templates = self.template_id
        res = super().write(vals)
        templates._bump_version()
        return res

    def unlink(self):
        templates = self.template_id
        res = super().unlink()
        templates._bump_version()
        return res

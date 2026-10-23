# -*- coding: utf-8 -*-

import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# 可以通过路径显示的字段类型 (与 ir.model.fields.ttype 一致)
SUPPORTED_TYPES = ('char', 'text', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime')


class MobileCustomField(models.Model):
    _name = 'mobile.custom.field'
    _description = "Custom Related Field"
    _order = 'sequence, id'

    name = fields.Char(string="Label", required=True)
    model_id = fields.Many2one('ir.model', string="Model", required=True, ondelete='cascade')
    model = fields.Char(related='model_id.model', readonly=True)
    path = fields.Char(
        string="Path", required=True,
        help="Dotted path of many2one fields ending with the field to show, e.g. doctor_id.hospital_id.address")
    store = fields.Boolean(
        string="Stored",
        help="Stored fields can be sorted and searched in the database. Changing this may need a server restart.")
    list_view = fields.Boolean(string="Show in list", default=True)
    sequence = fields.Integer(default=10)
    # 由配置生成的字段与视图, 随配置一起创建与删除
    field_name = fields.Char(string="Technical name", readonly=True, copy=False)
    field_id = fields.Many2one('ir.model.fields', readonly=True, copy=False, ondelete='set null')
    view_id = fields.Many2one('ir.ui.view', readonly=True, copy=False, ondelete='set null')

    @api.constrains('model_id', 'path')
    def _check_path(self):
        for record in self:
            record._target_field()

    def _target_field(self):
        """ Follow the dotted path from the model and return the field it ends with. """
        self.ensure_one()
        parts = [part.strip() for part in (self.path or '').split('.')]
        if not all(parts):
            raise ValidationError(_("The path is empty or has an empty step: %s", self.path))
        model = self.env[self.model_id.model]
        for part in parts[:-1]:
            field = model._fields.get(part)
            if not field or field.type != 'many2one':
                raise ValidationError(_("'%(part)s' must be a many2one field to follow the path %(path)s", part=part, path=self.path))
            model = self.env[field.comodel_name]
        field = model._fields.get(parts[-1])
        if not field:
            raise ValidationError(_("'%(part)s' is not a field of the path %(path)s", part=parts[-1], path=self.path))
        if field.type not in SUPPORTED_TYPES:
            raise ValidationError(_("The field '%(part)s' has the type %(type)s, which cannot be shown this way", part=parts[-1], type=field.type))
        return field

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._generate()
        return records

    def write(self, vals):
        regenerate = any(key in vals for key in ('model_id', 'path', 'store', 'list_view', 'name'))
        if not regenerate:
            return super().write(vals)
        self._remove_generated()
        result = super().write(vals)
        for record in self:
            record._generate()
        return result

    def unlink(self):
        self._remove_generated()
        return super().unlink()

    def _generate(self):
        """ Create the related manual field and, for list views, the inherited view that shows it. """
        self.ensure_one()
        field = self._target_field()
        if not self.field_name:
            base = 'x_mcf_' + re.sub(r'\W+', '_', self.path).strip('_').lower()
            name, counter = base, 1
            while self.env['ir.model.fields'].search_count([('model', '=', self.model), ('name', '=', name)]):
                counter += 1
                name = f'{base}_{counter}'
            self.field_name = name
        field_record = self.env['ir.model.fields'].create({
            'model_id': self.model_id.id,
            'name': self.field_name,
            'field_description': self.name,
            'ttype': field.type,
            'state': 'manual',
            'related': self.path,
            'store': self.store,
            'readonly': True,
        })
        view = self._generate_view()
        self.write({'field_id': field_record.id, 'view_id': view.id if view else False})

    def _generate_view(self):
        if not self.list_view:
            return None
        base_view = self.env['ir.ui.view'].search(
            [('model', '=', self.model), ('type', '=', 'list'), ('mode', '=', 'primary')], order='priority, id', limit=1)
        if not base_view:
            raise UserError(_("The model %s has no list view to show the field in.", self.model))
        arch = (
            f'<xpath expr="//list" position="inside">'
            f'<field name="{self.field_name}"/>'
            f'</xpath>'
        )
        return self.env['ir.ui.view'].create({
            'name': f'mobile.custom.field.{self.field_name}',
            'model': self.model,
            'inherit_id': base_view.id,
            'mode': 'extension',
            'priority': 99,
            'arch': arch,
        })

    def _remove_generated(self):
        for record in self:
            if record.view_id:
                record.view_id.unlink()
            if record.field_id:
                record.field_id.unlink()
        self.write({'field_id': False, 'view_id': False})

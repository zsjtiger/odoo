# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class IrModel(models.Model):
    _inherit = 'ir.model'

    supports_record_type = fields.Boolean(string='Supports Record Types', copy=False)
    record_type_ids = fields.One2many('ir.record.type', 'model_id', string='Record Types')

    def action_enable_record_type(self):
        for model in self:
            if model.supports_record_type:
                continue
            model._check_no_unscoped_grants()
            model._ensure_record_type_field()
            model._ensure_admin_grant()
            model.supports_record_type = True
        return True

    def action_disable_record_type(self):
        for model in self:
            if not model.supports_record_type:
                continue
            if model.model in self.env:
                used = self.env[model.model].sudo().with_context(active_test=False).search_count(
                    [('record_type_id', '!=', False)])
                if used:
                    raise UserError(self.env._(
                        "Model %(model)s still has %(count)s records with a record type. Record types cannot be disabled while they are in use.",
                        model=model.display_name, count=used,
                    ))
            model.record_type_ids.write({'active': False})
            model.supports_record_type = False
        return True

    def _check_no_unscoped_grants(self):
        """Enabling record types requires every non-admin grant on the model to be scoped to a type."""
        admin = self.env.ref('base.group_system')
        rows = self.env['ir.access'].sudo().search([
            ('model_id', 'in', self.ids),
            ('record_type_id', '=', False),
            ('group_id', '!=', False),
            ('group_id', '!=', admin.id),
            ('active', '=', True),
        ])
        if rows:
            raise UserError(self.env._(
                "Before enabling record types, scope or delete these grants: %(rows)s",
                rows=", ".join(f"{row.name} ({row.group_id.display_name}, {row.operation})" for row in rows),
            ))

    def _ensure_record_type_field(self):
        """The field comes from the model class (``_record_type = True``), not from metadata."""
        self.ensure_one()
        if self.model not in self.env or 'record_type_id' not in self.env[self.model]._fields:
            raise UserError(self.env._(
                "Model %(model)s must declare _record_type = True before record types can be enabled.",
                model=self.model,
            ))

    def _ensure_admin_grant(self):
        self.ensure_one()
        admin = self.env.ref('base.group_system')
        exists = self.env['ir.access'].sudo().search([
            ('model_id', '=', self.id), ('group_id', '=', admin.id),
            ('record_type_id', '=', False), ('domain', '=', False),
        ], limit=1)
        if not exists:
            self.env['ir.access'].sudo().create({
                'name': f"{self.model} / administrators",
                'model_id': self.id,
                'group_id': admin.id,
                'operation': 'crud',
            })

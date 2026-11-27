# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class IrDataImportPermission(models.Model):
    """Which groups may import into a model and download its template."""
    _name = 'ir.data.import.permission'
    _description = 'Data Import Permission'
    _order = 'model_id, group_id'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    group_id = fields.Many2one('res.groups', required=True, ondelete='cascade')
    allow_import = fields.Boolean(string='Import', default=True)
    perm_template = fields.Boolean(string='Download template', default=True)

    _model_group_unique = models.Constraint(
        'UNIQUE(model_id, group_id)', 'Only one import permission row per model and group.',
    )

    @api.constrains('allow_import', 'perm_template')
    def _check_one_permission(self):
        for record in self:
            if not (record.allow_import or record.perm_template):
                raise ValidationError(_('Grant at least one import permission.'))

    @api.model
    def _user_can(self, model_name, perm):
        """True if the current user may do perm ('allow_import' or 'perm_template') on the model."""
        if self.env.su or self.env.user.has_group('base.group_system'):
            return True
        model = self.env['ir.model']._get(model_name)
        if not model:
            return False
        rows = self.sudo().search([
            ('model_id', '=', model.id),
            ('group_id', 'in', self.env.user.all_group_ids.ids),
        ])
        return any(row[perm] for row in rows)

# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class IrRecordType(models.Model):
    _inherit = 'ir.record.type'

    allow_import = fields.Boolean(
        string='Allow import', default=True,
        help='Off: records of this type cannot be created, updated or deleted by import, for anyone.',
    )

    def _check_import_allowed(self):
        """Raise UserError if the current user may not import records of these types."""
        for record_type in self:
            if not record_type.allow_import:
                raise UserError(_('Record type %s does not allow import.', record_type.display_name))
            if self.env.su or self.env.user.has_group('base.group_system'):
                continue
            perms = self.env['ir.record.type.permission'].sudo().search([
                ('record_type_id', '=', record_type.id),
                ('group_id', 'in', self.env.user.all_group_ids.ids),
            ])
            if not any(perms.mapped('allow_import')):
                raise UserError(_('You are not allowed to import records of type %s.', record_type.display_name))


class IrRecordTypePermission(models.Model):
    _inherit = 'ir.record.type.permission'

    allow_import = fields.Boolean(
        string='Allow import', default=True,
        help='The group may create, update and delete records of this type through import.',
    )

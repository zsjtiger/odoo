# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import AccessError


class IrDataImportMixin(models.AbstractModel):
    """Add to a model (``_inherit = ['ir.data.import.mixin']``) to get the Import button action."""
    _name = 'ir.data.import.mixin'
    _description = 'Data Import Mixin'

    def action_open_data_import(self):
        perm = self.env['ir.data.import.permission']
        if not (perm._user_can(self._name, 'allow_import') or perm._user_can(self._name, 'perm_template')):
            raise AccessError(_('You are not allowed to import %s.', self.env[self._name]._description))
        model = self.env['ir.model']._get(self._name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import'),
            'res_model': 'ir.data.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_model_id': model.id},
        }

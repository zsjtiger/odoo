# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    record_type_id = fields.Many2one(
        'ir.record.type', string='Record Type', ondelete='cascade', index=True,
        help="If set, this view is the layout of records of this type.",
    )

    @api.constrains('record_type_id', 'model', 'type')
    def _check_record_type_view(self):
        for view in self:
            if not view.record_type_id:
                continue
            if view.record_type_id.model_name != view.model:
                raise ValidationError(self.env._(
                    "The view model %(view)s must be the model of record type %(type)s.",
                    view=view.model, type=view.record_type_id.display_name,
                ))
            if view.type != 'form':
                raise ValidationError(self.env._("Record type views must be form views."))

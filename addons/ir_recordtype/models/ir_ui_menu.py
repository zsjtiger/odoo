# -*- coding: utf-8 -*-
from odoo import fields, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    record_type_id = fields.Many2one(
        'ir.record.type', string='Record Type', ondelete='cascade', index=True,
        help="Menu generated for a record type.",
    )

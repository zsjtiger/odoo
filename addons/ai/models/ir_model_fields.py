from odoo import fields, models


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'

    ttype = fields.Selection(selection_add=[
        ('vector', 'vector'),
    ], ondelete={'vector': 'cascade'})

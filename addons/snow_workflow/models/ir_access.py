from odoo import fields, models


class IrAccess(models.Model):
    _inherit = "ir.access"

    perm_approval = fields.Boolean("Approval Access", default=False)

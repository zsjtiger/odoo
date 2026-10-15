from crossnow import fields, models


class IrModelAccess(models.Model):
    _inherit = "ir.model.access"

    perm_approval = fields.Boolean("Approval Access", default=False)

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Read by the native mobile app to fetch avatars (mobile_app/core/mixins.js)
    image_medium = fields.Binary(string="Medium-sized image", related='avatar_128', store=False, readonly=True)

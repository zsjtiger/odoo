# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # overridden inherited fields to bypass access rights, in case you have
    # access to the user but not its corresponding partner
    country_id = fields.Many2one(related='partner_id.country_id', inherited=True, readonly=False, user_writeable=True)
    city = fields.Char(related='partner_id.city', inherited=True, readonly=False, user_writeable=True)
    website = fields.Char(related='partner_id.website', inherited=True, readonly=False, user_writeable=True)
    website_description = fields.Html(related='partner_id.website_description', inherited=True, readonly=False, user_writeable=True)
    website_published = fields.Boolean(related='partner_id.website_published', inherited=True, readonly=False, user_writeable=True)

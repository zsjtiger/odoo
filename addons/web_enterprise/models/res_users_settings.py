# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResUsersSettings(models.Model):
    _inherit = 'res.users.settings'

    homemenu_config = fields.Json(string="Home Menu Configuration", readonly=True)
    color_scheme = fields.Selection(
        [("system", "System"), ("light", "Light"), ("dark", "Dark")],
        default="system",
        required=True,
        string="Color Scheme",
    )

    def write(self, vals):
        if 'color_scheme' in vals and not vals['color_scheme']:
            vals.pop('color_scheme')
        return super().write(vals)

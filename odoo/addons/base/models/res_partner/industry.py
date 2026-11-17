# Part of Odoo. See LICENSE file for full copyright and licensing details.

from __future__ import annotations
import typing
from odoo import fields, models

if typing.TYPE_CHECKING:
    pass

class ResPartnerIndustry(models.Model):
    _name = 'res.partner.industry'
    _description = 'Industry'
    _order = "name, id"

    name = fields.Char('Name', translate=True)
    full_name = fields.Char('Full Name', translate=True)
    active = fields.Boolean('Active', default=True)

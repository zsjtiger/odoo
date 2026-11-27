# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountDcr(models.Model):
    """DCR of a pharmacy. Its pharmacy information is copied from the pharmacy when it is created."""
    _name = 'pharaccount.dcr'
    _description = 'Pharmacy DCR'
    _order = 'id desc'

    name = fields.Char(required=True)
    pharmacy_id = fields.Many2one('pharaccount.account', string='Pharmacy', required=True,
                                  ondelete='cascade', index=True)
    pharmacy_record_type_id = fields.Many2one('ir.record.type', string='Record Type')
    pharmacy_level_id = fields.Many2one('pharaccount.picklist.value', string='Pharmacy level')
    state_id = fields.Many2one('pharaccount.account.state', string='State')
    mobile = fields.Char()
    telephone = fields.Char()
    geo_province = fields.Char(string='Province')
    geo_city = fields.Char(string='City')
    address = fields.Char()
    is_important = fields.Boolean(string='Important')
    description = fields.Text()

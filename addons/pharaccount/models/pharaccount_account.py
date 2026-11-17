# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PharaccountAccount(models.Model):
    """Pharmacy account, the main table. Mirrors the pharmacy part of vrux ``accounts``.

    vrux ``accounts`` also references picklists and itself. Here the picklist references
    point at ``pharaccount.picklist.value`` and the self references at this model.
    """
    _name = 'pharaccount.account'
    _description = 'Pharmacy Account'
    _order = 'name, id'

    name = fields.Char(required=True, index=True)
    alias = fields.Char()
    address = fields.Char()
    telephone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()
    description = fields.Text()
    last_called_on = fields.Date(string='Last called on')
    active = fields.Boolean(default=True)

    record_type_id = fields.Many2one(
        'pharaccount.record.type', string='Record type', required=True, index=True,
        domain="[('active', '=', True)]",
    )
    pharmacy_level_id = fields.Many2one(
        'pharaccount.picklist.value', string='Pharmacy level',
        domain="[('picklist_id.name', '=', 'pharmacy_level')]",
    )

    superior_id = fields.Many2one('pharaccount.account', string='Superior pharmacy', ondelete='set null')
    headquarters_id = fields.Many2one('pharaccount.account', string='Headquarters', ondelete='set null')
    hospital_id = fields.Many2one('pharaccount.account', string='Hospital', ondelete='set null')
    agency_id = fields.Many2one('pharaccount.account', string='Agency', ondelete='set null')
    dealer_id = fields.Many2one('pharaccount.account', string='Dealer', ondelete='set null')

    @api.onchange('record_type_id')
    def _onchange_record_type_id(self):
        """Drop the picklist value when it is not allowed for the new record type."""
        if self.pharmacy_level_id and self.record_type_id:
            allowed = self.env['pharaccount.picklist.value'].get_selectable(
                'pharmacy_level', self.record_type_id,
            )
            if self.pharmacy_level_id not in allowed:
                self.pharmacy_level_id = False

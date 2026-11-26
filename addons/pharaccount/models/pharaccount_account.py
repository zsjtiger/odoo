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
    _record_type = True  # adds record_type_id (ir.record.type); permissions come from the type

    name = fields.Char(required=True, index=True)
    alias = fields.Char()
    name_pinyin = fields.Char(string='Name pinyin', help='Pinyin of the name, used for search.')
    pinyin = fields.Char(help='Pinyin of the name without separators.')
    alias_pinyin = fields.Text(string='Alias pinyin')
    pinyin_with_separator = fields.Text(string='Pinyin with separator')
    address = fields.Char()
    geo_province = fields.Char(string='Province')
    geo_city = fields.Char(string='City')
    geo_district = fields.Char(string='District')
    telephone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()
    description = fields.Text()
    creation_time = fields.Date(string='Creation time', default=fields.Date.context_today)
    last_called_on = fields.Date(string='Last called on')
    sales = fields.Float(string='Sales')
    is_important = fields.Boolean(string='Important')
    is_public = fields.Boolean(string='Public')
    authorized_packages = fields.Char(string='Authorized packages')
    openid = fields.Char(string='WeChat openid')
    openid_register_time = fields.Datetime(string='WeChat binding time')
    account_distributer_code = fields.Char(string='Distributor code')
    active = fields.Boolean(default=True)

    state_id = fields.Many2one('pharaccount.account.state', string='State', index=True)

    pharmacy_level_id = fields.Many2one(
        'pharaccount.picklist.value', string='Pharmacy level',
        domain="[('picklist_id.name', '=', 'pharmacy_level')]",
    )

    superior_id = fields.Many2one('pharaccount.account', string='Superior pharmacy', ondelete='set null')
    headquarters_id = fields.Many2one('pharaccount.account', string='Headquarters', ondelete='set null')
    hospital_id = fields.Many2one('pharaccount.account', string='Hospital', ondelete='set null')
    agency_id = fields.Many2one('pharaccount.account', string='Agency', ondelete='set null')
    dealer_id = fields.Many2one('pharaccount.account', string='Dealer', ondelete='set null')

    staff_ids = fields.One2many('pharaccount.pharmacy.staff', 'pharmacy_id', string='Staff')
    hospital_link_ids = fields.One2many('pharaccount.hospital.link', 'pharmacy_id', string='Hospital links')
    pharma_link_ids = fields.One2many('pharaccount.hospital.link', 'hospital_id', string='Linked pharmacies')
    package_inventory_ids = fields.One2many('pharaccount.package.inventory', 'pharmacy_id',
                                            string='Package inventory')
    competitive_product_ids = fields.One2many('pharaccount.competitive.product', 'pharmacy_id',
                                              string='Competitive products')

    @api.onchange('record_type_id')
    def _onchange_record_type_id(self):
        """Drop the picklist value when it is not allowed for the new record type."""
        if self.pharmacy_level_id and self.record_type_id:
            allowed = self.env['pharaccount.picklist.value'].get_selectable(
                'pharmacy_level', self.record_type_id,
            )
            if self.pharmacy_level_id not in allowed:
                self.pharmacy_level_id = False

    def action_new_staff(self):
        """Open a new staff form for this pharmacy, with the pharmacy and its telephone filled in."""
        self.ensure_one()
        self.env['pharaccount.pharmacy.staff'].check_access('create')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('New Staff'),
            'res_model': 'pharaccount.pharmacy.staff',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_pharmacy_id': self.id,
                'default_name': self.name,
                'default_telephone': self.telephone or self.mobile,
            },
        }

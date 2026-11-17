# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountPackageInventory(models.Model):
    """Monthly stock of a package in a pharmacy. Mirrors vrux ``account_package_inventories``.

    ``package`` is text until the packages model is migrated.
    """
    _name = 'pharaccount.package.inventory'
    _description = 'Pharmacy Package Inventory'
    _order = 'pharmacy_id, inventory_date desc, id'

    pharmacy_id = fields.Many2one('pharaccount.account', string='Pharmacy', required=True,
                                  ondelete='cascade', index=True)
    inventory_date = fields.Date(string='Inventory date')
    yearmonth = fields.Char(string='Year-month', help='For example 2026-11.')
    package = fields.Char()
    quantity_in = fields.Integer(string='Purchased')
    quantity_out = fields.Integer(string='Sold')
    stock = fields.Integer()

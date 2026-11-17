# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountCompetitiveProduct(models.Model):
    """Competing product seen in a pharmacy. Mirrors vrux ``account_competitive_products``.

    ``product`` and ``competitive_product`` are text until the products models are migrated.
    """
    _name = 'pharaccount.competitive.product'
    _description = 'Pharmacy Competitive Product'
    _order = 'pharmacy_id, id'

    pharmacy_id = fields.Many2one('pharaccount.account', string='Pharmacy', required=True,
                                  ondelete='cascade', index=True)
    product = fields.Char(string='Our product', required=True)
    competitive_product = fields.Char(string='Competitor product', required=True)
    price = fields.Float()
    sales_quantity = fields.Integer(string='Sales quantity', default=0)
    comments = fields.Text()

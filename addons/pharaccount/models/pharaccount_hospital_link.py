# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountHospitalLink(models.Model):
    """A pharmacy supplies a package to a hospital. Mirrors vrux ``pharma_hospital_links``.

    ``year`` and ``month`` are text here, and ``package`` is text until the packages
    model is migrated, because vrux points at picklist values and a packages table.
    """
    _name = 'pharaccount.hospital.link'
    _description = 'Pharmacy Hospital Link'
    _order = 'pharmacy_id, hospital_id, id'

    pharmacy_id = fields.Many2one('pharaccount.account', string='Pharmacy', required=True,
                                  ondelete='cascade', index=True)
    hospital_id = fields.Many2one('pharaccount.account', string='Hospital', required=True,
                                  ondelete='cascade', index=True)
    year = fields.Char()
    month = fields.Char()
    package = fields.Char()
    proportion = fields.Float(default=1.0)
    external_id = fields.Char(index=True)

# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountPharmacyStaff(models.Model):
    """Staff of a pharmacy. Mirrors vrux ``pharmacy_staffs``.

    The picklist values use the vrux picklists ``pharmacy_staff_type``, ``gender`` and
    ``pharmacy_staff_in_service_status``. Shift times are multi-select in vrux, so they
    are stored as text here.
    """
    _name = 'pharaccount.pharmacy.staff'
    _description = 'Pharmacy Staff'
    _order = 'pharmacy_id, id'

    name = fields.Char(required=True)
    pharmacy_id = fields.Many2one('pharaccount.account', string='Pharmacy', required=True,
                                  ondelete='cascade', index=True)
    staff_type_id = fields.Many2one(
        'pharaccount.picklist.value', string='Position',
        domain="[('picklist_id.name', '=', 'pharmacy_staff_type')]",
    )
    gender_id = fields.Many2one(
        'pharaccount.picklist.value', string='Gender',
        domain="[('picklist_id.name', '=', 'gender')]",
    )
    age = fields.Char()
    telephone = fields.Char()
    shift_time = fields.Char(string='Shift time', help='Comma separated shift days.')
    in_service_status_id = fields.Many2one(
        'pharaccount.picklist.value', string='In service status',
        domain="[('picklist_id.name', '=', 'pharmacy_staff_in_service_status')]",
    )
    description = fields.Char()

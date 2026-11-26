# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Pharmacy record types as in vrux (object_record_types): a parent and its children.
DEFAULT_RECORD_TYPES = [
    # code, label, sequence, parent code
    ('pharma', '药店', 1, False),
    ('pharmacy_chain_head', '连锁总店', 10, 'pharma'),
    ('pharmacy_chain_branch', '连锁门店', 20, 'pharma'),
    ('pharmacy_monomer', '单体药店', 30, 'pharma'),
]


class IrRecordType(models.Model):
    """Pharmacy-specific extension of a record type: the picklist options it allows."""
    _inherit = 'ir.record.type'

    picklist_value_ids = fields.Many2many(
        'pharaccount.picklist.value', 'pharaccount_ir_record_type_picklist_value_rel',
        'record_type_id', 'value_id', string='Own picklist values',
        help="Picklist options usable with this record type. Empty means no restriction.",
    )
    allowed_picklist_value_ids = fields.Many2many(
        'pharaccount.picklist.value', compute='_compute_allowed_picklist_value_ids', store=True,
        string='Allowed picklist values',
        help="Own options plus the options of the parent types (union).",
    )

    @api.depends('picklist_value_ids', 'parent_id.allowed_picklist_value_ids')
    def _compute_allowed_picklist_value_ids(self):
        for record in self:
            record.allowed_picklist_value_ids = record.picklist_value_ids | record.parent_id.allowed_picklist_value_ids

    @api.model
    def _pharaccount_create_default_types(self):
        """Create the pharmacy types on install. Existing types are left untouched."""
        model = self.env['ir.model']._get('pharaccount.account')
        created = self.browse()
        for code, label, sequence, parent_code in DEFAULT_RECORD_TYPES:
            record_type = self.search([('model_id', '=', model.id), ('code', '=', code)], limit=1)
            if not record_type:
                record_type = self.create({'name': label, 'code': code, 'model_id': model.id, 'sequence': sequence})
                created |= record_type
            if parent_code and not record_type.parent_id:
                record_type.parent_id = self.search([('model_id', '=', model.id), ('code', '=', parent_code)], limit=1)
        return created

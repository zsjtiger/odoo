# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Pharmacy record types as in vrux (object_record_types): a parent and its children.
DEFAULT_RECORD_TYPES = [
    # code, label, sequence, parent code
    ('pharma', '药店', 1, False),
    ('pharmacy_chain_head', '连锁总店', 10, 'pharma'),
    ('pharmacy_chain_branch', '连锁门店', 20, 'pharma'),
    ('pharmacy_monomer', '单体药店', 30, 'pharma'),
    # shared pharmacy account model, other record types of the same model
    ('hospital', '医院', 40, False),
    ('doctor', '医生', 50, False),
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
    def _pharaccount_grant_pharmacy_access(self, record_type):
        """The pharmacy type is granted to the user groups like the others, if it has no permission yet."""
        if record_type.permission_ids:
            return
        self.env['ir.record.type.permission'].create([
            {'record_type_id': record_type.id, 'group_id': self.env.ref('pharaccount.group_user').id,
             'perm_read': True, 'perm_write': True, 'perm_create': True},
            {'record_type_id': record_type.id, 'group_id': self.env.ref('pharaccount.group_manager').id,
             'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': True},
        ])

    @api.model
    def _pharaccount_create_default_types(self):
        """Create the pharmacy record types that do not exist yet.

        A new type gets the default access (group_user reads, writes and creates; group_manager
        also deletes) and the group_user default goes to the pharmacy type if there is none.
        Existing types and their configuration are left untouched.
        """
        model = self.env['ir.model']._get('pharaccount.account')
        group_user = self.env.ref('pharaccount.group_user')
        group_manager = self.env.ref('pharaccount.group_manager')
        root_menu = self.env.ref('pharaccount.menu_pharaccount_pc_root')
        Permission = self.env['ir.record.type.permission']
        Default = self.env['ir.record.type.default']
        created = self.browse()
        for code, label, sequence, parent_code in DEFAULT_RECORD_TYPES:
            record_type = self.search([('model_id', '=', model.id), ('code', '=', code)], limit=1)
            if not record_type:
                record_type = self.create({'name': label, 'code': code, 'model_id': model.id, 'sequence': sequence})
                created |= record_type
                Permission.create([
                    {'record_type_id': record_type.id, 'group_id': group_user.id,
                     'perm_read': True, 'perm_write': True, 'perm_create': True},
                    {'record_type_id': record_type.id, 'group_id': group_manager.id,
                     'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': True},
                ])
            if parent_code and not record_type.parent_id:
                record_type.parent_id = self.search([('model_id', '=', model.id), ('code', '=', parent_code)], limit=1)
            # the types are shown under the pharmacy root menu
            if not record_type.menu_parent_id:
                record_type.menu_parent_id = root_menu
        pharma = self.search([('model_id', '=', model.id), ('code', '=', 'pharma')], limit=1)
        if pharma:
            self._pharaccount_grant_pharmacy_access(pharma)
        # a default must be granted to its group, so it is only set when the type grants group_user
        if (pharma and pharma.permission_ids.filtered(lambda p: p.group_id == group_user)
                and not Default.search([('model_id', '=', model.id), ('group_id', '=', group_user.id)], limit=1)):
            Default.create({'model_id': model.id, 'group_id': group_user.id, 'record_type_id': pharma.id})
        return created

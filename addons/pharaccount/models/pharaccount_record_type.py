# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PharaccountRecordType(models.Model):
    """Record type of a pharmacy account. Mirrors vrux ``object_record_types``.

    A child record type inherits its parent's allowed groups and picklist values.
    The effective value is the union of the parent's and the child's own configuration,
    so a child can add options but cannot remove the parent's.
    """
    _name = 'pharaccount.record.type'
    _description = 'Pharmacy Record Type'
    _parent_name = 'parent_id'
    _order = 'sequence, id'

    name = fields.Char(required=True, help='Technical code, e.g. pharmacy_monomer')
    label = fields.Char(required=True, help='Shown to users, e.g. 单体药店')
    sequence = fields.Integer(default=10)
    code_prefix = fields.Char()
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one('pharaccount.record.type', string='Parent type', ondelete='restrict', index=True)
    child_ids = fields.One2many('pharaccount.record.type', 'parent_id', string='Child types')
    ir_record_type_id = fields.Many2one(
        'ir.record.type', string='Record type (framework)', ondelete='set null', index=True, copy=False,
        help="The generic ir.record.type this legacy type is mirrored to (see _sync_to_record_types).",
    )

    group_ids = fields.Many2many(
        'res.groups', 'pharaccount_record_type_group_rel', 'record_type_id', 'group_id',
        string='Own allowed groups',
        help='Groups that can use this record type. Inherited groups are added automatically.',
    )
    allowed_group_ids = fields.Many2many(
        'res.groups', compute='_compute_allowed', store=True, string='Allowed groups',
        help='Own groups plus the groups of the parent types (union).',
    )
    has_group_restriction = fields.Boolean(
        compute='_compute_allowed', store=True,
        help='True when some group is configured. A record type without groups is open to everyone.',
    )
    picklist_value_ids = fields.Many2many(
        'pharaccount.picklist.value', 'pharaccount_record_type_picklist_value_rel',
        'record_type_id', 'value_id', string='Own picklist values',
        help='Picklist options that can be used with this record type. Empty means no restriction.',
    )
    allowed_picklist_value_ids = fields.Many2many(
        'pharaccount.picklist.value', compute='_compute_allowed', store=True,
        string='Allowed picklist values', help='Own options plus the options of the parent types (union).',
    )

    _name_unique = models.Constraint('UNIQUE(name)', 'The record type code must be unique.')

    @api.depends('group_ids', 'picklist_value_ids', 'parent_id.allowed_group_ids',
                 'parent_id.allowed_picklist_value_ids')
    def _compute_allowed(self):
        for record in self:
            parent = record.parent_id
            record.allowed_group_ids = record.group_ids | parent.allowed_group_ids
            record.allowed_picklist_value_ids = record.picklist_value_ids | parent.allowed_picklist_value_ids
            record.has_group_restriction = bool(record.allowed_group_ids)

    @api.constrains('parent_id')
    def _check_parent_cycle(self):
        if not self._has_cycle():
            return
        raise ValidationError(self.env._('A record type cannot be its own ancestor.'))

    @api.model
    def _sync_to_record_types(self):
        """Mirror the legacy types into ir.record.type (idempotent).

        - one ir.record.type per legacy type, linked through ``ir_record_type_id``;
        - each legacy group becomes a permission: read/write/create, and delete for the manager group;
        - accounts are pointed to the new type (legacy type kept in ``legacy_record_type_id``);
        - then the model is enabled for record types.
        """
        RecordType = self.env['ir.record.type'].sudo()
        Permission = self.env['ir.record.type.permission'].sudo()
        model = self.env['ir.model']._get('pharaccount.account')
        manager = self.env.ref('pharaccount.group_manager')
        legacy_types = self.sudo().with_context(active_test=False).search([])

        for legacy in legacy_types:
            record_type = legacy.ir_record_type_id or RecordType.search(
                [('model_id', '=', model.id), ('code', '=', legacy.name)], limit=1)
            vals = {'name': legacy.label, 'code': legacy.name, 'model_id': model.id,
                    'sequence': legacy.sequence, 'active': legacy.active}
            if record_type:
                record_type.write(vals)
            else:
                record_type = RecordType.create(vals)
            legacy.ir_record_type_id = record_type

            for group in legacy.group_ids:
                perm = Permission.search([('record_type_id', '=', record_type.id), ('group_id', '=', group.id)])
                perm_vals = {'perm_read': True, 'perm_write': True, 'perm_create': True,
                             'perm_unlink': group == manager}
                if perm:
                    perm.write(perm_vals)
                else:
                    Permission.create(perm_vals | {'record_type_id': record_type.id, 'group_id': group.id})

        # parents after all types exist
        for legacy in legacy_types:
            if legacy.parent_id:
                legacy.ir_record_type_id.parent_id = legacy.parent_id.ir_record_type_id

        # point accounts to the new type, through the legacy type they had
        Account = self.env['pharaccount.account'].sudo()
        for legacy in legacy_types:
            accounts = Account.search([
                ('legacy_record_type_id', '=', legacy.id), ('record_type_id', '=', False),
            ])
            accounts.write({'record_type_id': legacy.ir_record_type_id.id})

        model.action_enable_record_type()
        return True


# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IrRecordTypePermission(models.Model):
    """Permission of a group on a record type. Each row generates one ir.access row."""
    _name = 'ir.record.type.permission'
    _description = 'Record Type Permission'

    record_type_id = fields.Many2one('ir.record.type', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one(related='record_type_id.model_id', store=True, readonly=True, index=True)
    group_id = fields.Many2one('res.groups', required=True, ondelete='cascade', index=True)
    perm_read = fields.Boolean(default=True)
    perm_write = fields.Boolean()
    perm_create = fields.Boolean()
    perm_unlink = fields.Boolean()
    access_id = fields.Many2one('ir.access', readonly=True, copy=False, ondelete='set null')

    _type_group_unique = models.Constraint('UNIQUE(record_type_id, group_id)', 'One permission per group and type.')

    @api.constrains('perm_read', 'perm_write', 'perm_create', 'perm_unlink')
    def _check_some_permission(self):
        for perm in self:
            if not (perm.perm_read or perm.perm_write or perm.perm_create or perm.perm_unlink):
                raise ValidationError(self.env._("A permission must allow at least one operation."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_access()
        records.record_type_id._sync_menu_groups()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_access()
        self.record_type_id._sync_menu_groups()
        return res

    def unlink(self):
        accesses = self.access_id
        types = self.record_type_id
        groups = self.group_id
        res = super().unlink()
        accesses.unlink()
        # defaults only make sense for groups that can still use the type
        for record_type in types:
            still_granted = record_type.permission_ids.group_id
            record_type.default_ids.filtered(lambda d: d.group_id in groups and d.group_id not in still_granted).unlink()
        types._sync_menu_groups()
        return res

    def _sync_access(self):
        Access = self.env['ir.access'].sudo()
        for perm in self:
            operation = ''.join(letter for letter, flag in (
                ('c', perm.perm_create), ('r', perm.perm_read), ('u', perm.perm_write), ('d', perm.perm_unlink),
            ) if flag)
            record_type = perm.record_type_id
            vals = {
                'name': f"{record_type.code} / {perm.group_id.display_name}",
                'model_id': record_type.model_id.id,
                'group_id': perm.group_id.id,
                'operation': operation,
                'domain': f"[('record_type_id', '=', {record_type.id})]",
                'record_type_id': record_type.id,
            }
            if perm.access_id:
                perm.access_id.write(vals)
            else:
                perm.access_id = Access.create(vals)

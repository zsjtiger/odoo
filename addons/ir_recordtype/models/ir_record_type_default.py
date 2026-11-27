# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IrRecordTypeDefault(models.Model):
    """Default record type of a group for a model, same idea as ir.default."""
    _name = 'ir.record.type.default'
    _description = 'Record Type Default'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    group_id = fields.Many2one('res.groups', required=True, ondelete='cascade', index=True)
    record_type_id = fields.Many2one('ir.record.type', required=True, ondelete='cascade', index=True)

    _model_group_unique = models.Constraint('UNIQUE(model_id, group_id)', 'One default per group and model.')

    @api.constrains('model_id', 'group_id', 'record_type_id')
    def _check_default(self):
        for default in self:
            if default.record_type_id.model_id != default.model_id:
                raise ValidationError(self.env._("The default type must belong to the same model."))
            if default.group_id not in default.record_type_id.permission_ids.group_id:
                raise ValidationError(self.env._("The default type must be granted to the group first."))

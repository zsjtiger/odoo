# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IrAccess(models.Model):
    _inherit = 'ir.access'

    record_type_id = fields.Many2one(
        'ir.record.type', string='Record Type', ondelete='cascade', index=True,
        help="If set, this access row only applies to records of this type.",
    )

    @api.constrains('record_type_id', 'model_id', 'group_id')
    def _check_record_type_scope(self):
        admin = self.env.ref('base.group_system')
        for access in self:
            if access.record_type_id and access.record_type_id.model_id != access.model_id:
                raise ValidationError(self.env._(
                    "Record type %(type)s does not belong to model %(model)s.",
                    type=access.record_type_id.display_name, model=access.model_id.display_name,
                ))
            # on a model with record types, non-admin grants must be scoped to a type,
            # otherwise an unscoped OR grant makes the type restriction ineffective
            if (access.group_id and access.group_id != admin and not access.record_type_id
                    and access.model_id.supports_record_type):
                raise ValidationError(self.env._(
                    "Model %(model)s supports record types: grants for group %(group)s must be scoped to a record type.",
                    model=access.model_id.display_name, group=access.group_id.display_name,
                ))

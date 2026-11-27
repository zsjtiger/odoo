# -*- coding: utf-8 -*-
from odoo import api, models


class Base(models.AbstractModel):
    """Behaviour of record types for models that have opted in (ir.model.supports_record_type).

    Models that merely have a ``record_type_id`` field (ir.access, ir.ui.menu, ir.ui.view) are
    not affected: they are not record-typed models themselves.
    """
    _inherit = 'base'

    def _record_type_enabled(self):
        return bool(self.env['ir.model']._get(self._name).supports_record_type) and 'record_type_id' in self._fields

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'record_type_id' in fields_list and not res.get('record_type_id') and self._record_type_enabled():
            record_type = self.env['ir.record.type']._get_default_for_user(self._name)
            if record_type:
                res['record_type_id'] = record_type.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        if self._record_type_enabled():
            RecordType = self.env['ir.record.type']
            for vals in vals_list:
                if vals.get('record_type_id'):
                    RecordType.browse(vals['record_type_id'])._check_can_use(self._name, 'create')
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('record_type_id') and self and self._record_type_enabled():
            changed = self.filtered(lambda r: r.record_type_id.id != vals['record_type_id'])
            if changed:
                self.env['ir.record.type'].browse(vals['record_type_id'])._check_can_use(self._name, 'write')
        return super().write(vals)

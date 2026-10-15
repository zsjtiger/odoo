# -*- coding: utf-8 -*-
from odoo import api, models


class GpsMixin(models.AbstractModel):
    """ 使用 gps 位置的模型继承此 mixin, 每个 many2one(gps) 字段对应该记录自己的一条位置 """
    _name = 'gps.mixin'
    _description = "GPS Owner Mixin"

    def _gps_field_names(self):
        return [name for name, field in self._fields.items()
                if field.type == 'many2one' and field.comodel_name == 'gps']

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._gps_link_owners()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._gps_link_owners()
        return result

    def _gps_link_owners(self):
        """ 把位置的所属记录设为当前记录 (新建记录保存后 res_id 才有值) """
        for name in self._gps_field_names():
            for record in self:
                gps = record[name]
                if gps and (gps.res_model, gps.res_id, gps.res_field) != (self._name, record.id, name):
                    # 该字段原来的位置已经不再被引用 (位置是独占的), 直接删除, 不留给定时任务
                    self.env['gps'].search([
                        ('id', '!=', gps.id),
                        ('res_model', '=', self._name),
                        ('res_id', '=', record.id),
                        ('res_field', '=', name),
                    ]).unlink()
                    gps.write({'res_model': self._name, 'res_id': record.id, 'res_field': name})

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        default = default or {}
        for record, vals in zip(self, vals_list):
            for name in self._gps_field_names():
                if name in default or not record[name]:
                    continue
                # 副本拥有自己的位置, 不能与原记录共用
                vals[name] = record[name].copy({'res_model': False, 'res_id': 0, 'res_field': False}).id
        return vals_list

    def unlink(self):
        locations = self.env['gps']
        for name in self._gps_field_names():
            locations |= self.mapped(name)
        result = super().unlink()
        # 只删除所属记录是本次删除的记录的位置
        (locations.exists().filtered(lambda gps: gps.res_model == self._name and gps.res_id in self.ids)).unlink()
        return result

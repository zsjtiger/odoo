# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# 没有被所属记录引用的位置, 超过这个时间后才会被清理 (避免删除正在编辑的表单中的位置)
ORPHAN_GRACE_PERIOD = timedelta(hours=24)


class Gps(models.Model):
    _name = 'gps'
    _description = "GPS Location"
    _order = 'id'

    address = fields.Char(string="Address")
    latitude = fields.Float(string="Latitude", digits=(10, 7))
    longitude = fields.Float(string="Longitude", digits=(10, 7))
    source = fields.Selection(
        [('search', "Search"), ('map', "Map"), ('device', "Device"), ('manual', "Manual")],
        string="Source", default='manual',
    )
    # 所属记录: 模型名、记录 id 与指向本位置的 many2one 字段名.
    # 新建时所属记录还没有保存, res_id 为 0, 保存所属记录时由 gps.mixin 补上.
    res_model = fields.Char(string="Owner model", index=True)
    res_id = fields.Integer(string="Owner ID", index=True)
    res_field = fields.Char(string="Owner field")

    @api.depends('address', 'latitude', 'longitude')
    def _compute_display_name(self):
        for gps in self:
            gps.display_name = gps.address or f"{gps.latitude}, {gps.longitude}"

    @api.constrains('latitude', 'longitude')
    def _check_coordinates(self):
        for gps in self:
            if not -90 <= gps.latitude <= 90:
                raise ValidationError(f"Latitude {gps.latitude} is out of range (-90 to 90).")
            if not -180 <= gps.longitude <= 180:
                raise ValidationError(f"Longitude {gps.longitude} is out of range (-180 to 180).")

    @api.constrains('res_model', 'res_id', 'res_field')
    def _check_owner_unique(self):
        # 一个所属记录的一个字段只能对应一条位置 (res_id 为 0 的未保存记录不参与检查)
        for gps in self.filtered('res_id'):
            duplicate = self.search_count([
                ('id', '!=', gps.id),
                ('res_model', '=', gps.res_model),
                ('res_id', '=', gps.res_id),
                ('res_field', '=', gps.res_field),
            ])
            if duplicate:
                raise ValidationError("This owner already has a location for this field.")

    def _get_owner(self):
        """ 所属记录, 不存在时返回空记录 """
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return self.env[self._name].browse()
        return self.env[self.res_model].browse(self.res_id).exists()

    @api.model
    def _cron_cleanup_orphans(self):
        """ 删除超过宽限期、且所属记录已不再引用它的位置 """
        cutoff = fields.Datetime.now() - ORPHAN_GRACE_PERIOD
        orphans = self.browse()
        for gps in self.search([('create_date', '<', cutoff)]):
            owner = gps._get_owner()
            if not owner or gps.res_field not in owner._fields or owner[gps.res_field].id != gps.id:
                orphans |= gps
        orphans.unlink()
        return len(orphans)

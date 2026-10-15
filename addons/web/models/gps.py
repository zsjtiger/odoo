# -*- coding: utf-8 -*-
import json
import logging
import urllib.parse
import urllib.request
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# 地址搜索与逆地理编码的服务地址, 可以在系统参数中改为自建的 Nominatim 服务
GEOCODER_URL_PARAM = 'web.gps.geocoder_url'
DEFAULT_GEOCODER_URL = 'https://nominatim.openstreetmap.org'
GEOCODER_TIMEOUT = 5

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 同一所属字段新建位置时, 原来的位置已被替换 (例如上一次编辑取消后遗留的未保存位置), 删除它
            if vals.get('res_model') and vals.get('res_id') and vals.get('res_field'):
                self.search([
                    ('res_model', '=', vals['res_model']),
                    ('res_id', '=', vals['res_id']),
                    ('res_field', '=', vals['res_field']),
                ]).unlink()
        return super().create(vals_list)

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

    # -------------------------------------------------------------------------
    # 地址搜索与逆地理编码 (前端控件调用, 第三方服务的请求在服务端发出)
    # -------------------------------------------------------------------------

    @api.model
    def _gps_request(self, path, params):
        """ 请求地理编码服务, 失败时返回 None (不抛出异常, 前端显示为没有结果) """
        base_url = self.env['ir.config_parameter'].sudo().get_param(GEOCODER_URL_PARAM) or DEFAULT_GEOCODER_URL
        url = f"{base_url.rstrip('/')}/{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={'User-Agent': 'Odoo-GPS/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=GEOCODER_TIMEOUT) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception:
            _logger.warning("GPS geocoder request failed: %s", url, exc_info=True)
            return None

    @api.model
    def search_address(self, query, limit=8):
        """ 按关键词搜索地址, 返回 [{address, latitude, longitude}] """
        query = (query or '').strip()
        if not query:
            return []
        items = self._gps_request('search', {
            'q': query,
            'format': 'json',
            'limit': int(limit),
            'accept-language': self.env.lang or 'en',
        })
        results = []
        for item in items or []:
            try:
                results.append({
                    'address': item['display_name'],
                    'latitude': float(item['lat']),
                    'longitude': float(item['lon']),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return results

    @api.model
    def reverse_address(self, latitude, longitude):
        """ 由坐标查询地址, 返回 {address, latitude, longitude} 或空字典 """
        item = self._gps_request('reverse', {
            'lat': latitude,
            'lon': longitude,
            'format': 'json',
            'accept-language': self.env.lang or 'en',
        })
        if not item or 'display_name' not in item:
            return {}
        return {'address': item['display_name'], 'latitude': latitude, 'longitude': longitude}

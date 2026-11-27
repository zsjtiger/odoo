# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGps(TransactionCase):

    def _gps(self, **vals):
        values = {'address': "北京市朝阳区建国路 88 号", 'latitude': 39.9042, 'longitude': 116.4074}
        values.update(vals)
        return self.env['gps'].create(values)

    def test_display_name_is_the_address(self):
        self.assertEqual(self._gps().display_name, "北京市朝阳区建国路 88 号")

    def test_display_name_falls_back_to_coordinates(self):
        gps = self._gps(address=False)
        self.assertIn("39.9042", gps.display_name)

    def test_latitude_out_of_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._gps(latitude=91)

    def test_longitude_out_of_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._gps(longitude=-181)

    def test_one_owner_field_has_one_location(self):
        # 新建时会替换同一所属字段的原位置, 唯一性约束在改写所属关系时检查
        first = self._gps(res_model='gps.owner.test', res_id=5, res_field='gps_id')
        other = self._gps(res_model='gps.owner.test', res_id=6, res_field='gps_id')
        with self.assertRaises(ValidationError):
            other.write({'res_id': first.res_id})
    def test_unsaved_owners_do_not_conflict(self):
        # 新建记录的位置 res_id 为 0, 多条都允许存在
        self._gps(res_model='gps.owner.test', res_id=0, res_field='gps_id')
        self._gps(res_model='gps.owner.test', res_id=0, res_field='gps_id')

    def test_cron_keeps_recent_locations(self):
        gps = self._gps(res_model='gps.owner.test', res_id=9, res_field='gps_id')
        self.env['gps']._cron_cleanup_orphans()
        self.assertTrue(gps.exists())

    def test_cron_removes_old_unreferenced_locations(self):
        gps = self._gps(res_model='res.partner', res_id=0, res_field='gps_id')
        self.env.cr.execute(
            "UPDATE gps SET create_date = %s WHERE id = %s",
            (fields.Datetime.now().replace(year=2000), gps.id),
        )
        self.env['gps']._cron_cleanup_orphans()
        self.assertFalse(gps.exists())

    def test_search_address_parses_the_geocoder_results(self):
        geocoder = [{'display_name': "北京市朝阳区建国路", 'lat': '39.9042', 'lon': '116.4074'}]
        with patch.object(type(self.env['gps']), '_gps_request', return_value=geocoder) as request:
            results = self.env['gps'].search_address("建国路")
        self.assertEqual(results, [{'address': "北京市朝阳区建国路", 'latitude': 39.9042, 'longitude': 116.4074}])
        self.assertEqual(request.call_args.args[0], 'search')

    def test_search_address_skips_malformed_items(self):
        geocoder = [{'display_name': "No coordinates"}, {'display_name': "OK", 'lat': '1', 'lon': '2'}]
        with patch.object(type(self.env['gps']), '_gps_request', return_value=geocoder):
            results = self.env['gps'].search_address("x")
        self.assertEqual([item['address'] for item in results], ["OK"])

    def test_search_address_without_query_makes_no_request(self):
        with patch.object(type(self.env['gps']), '_gps_request') as request:
            self.assertEqual(self.env['gps'].search_address("   "), [])
        request.assert_not_called()

    def test_search_address_failure_returns_no_results(self):
        with patch.object(type(self.env['gps']), '_gps_request', return_value=None):
            self.assertEqual(self.env['gps'].search_address("anything"), [])

    def test_reverse_address_returns_the_address_of_the_point(self):
        item = {'display_name': "北京市朝阳区建国路"}
        with patch.object(type(self.env['gps']), '_gps_request', return_value=item):
            result = self.env['gps'].reverse_address(39.9, 116.4)
        self.assertEqual(result, {'address': "北京市朝阳区建国路", 'latitude': 39.9, 'longitude': 116.4})

    def test_reverse_address_without_result_is_empty(self):
        with patch.object(type(self.env['gps']), '_gps_request', return_value=None):
            self.assertEqual(self.env['gps'].reverse_address(0, 0), {})

    def test_creating_a_location_replaces_the_previous_one_of_the_same_owner_field(self):
        first = self._gps(res_model='gps.owner.test', res_id=7, res_field='gps_id')
        second = self._gps(address="Replacement", res_model='gps.owner.test', res_id=7, res_field='gps_id')
        self.assertFalse(first.exists())
        self.assertEqual(second.res_id, 7)

    def _set_map_key(self, value):
        self.env['ir.config_parameter'].sudo().set_str('web.gps.amap_key', value or '')

    def test_map_config_is_empty_without_a_key(self):
        self._set_map_key(False)
        self.assertEqual(self.env['gps'].get_map_config(), {})

    def test_map_config_exposes_the_configured_key(self):
        self._set_map_key('demo-key')
        self.assertEqual(self.env['gps'].get_map_config(), {'provider': 'amap', 'key': 'demo-key'})

    def test_geocoder_request_uses_the_configured_service_url(self):
        self.env['ir.config_parameter'].sudo().set_str('web.gps.geocoder_url', 'https://geo.example.com/')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[]'
        with patch('urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(self.env['gps'].search_address("建国路"), [])
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://geo.example.com/search?'))
        self.assertIn('q=%E5%BB%BA%E5%9B%BD%E8%B7%AF', request.full_url)

    def test_settings_save_the_gps_parameters(self):
        settings = self.env['res.config.settings'].create({
            'gps_amap_key': 'demo-key',
            'gps_geocoder_url': 'https://geo.example.com/',
        })
        settings.execute()
        params = self.env['ir.config_parameter'].sudo()
        self.assertEqual(params.get_str('web.gps.amap_key'), 'demo-key')
        self.assertEqual(params.get_str('web.gps.geocoder_url'), 'https://geo.example.com/')

    def test_settings_read_the_gps_parameters(self):
        self.env['ir.config_parameter'].sudo().set_str('web.gps.amap_key', 'stored-key')
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.gps_amap_key, 'stored-key')

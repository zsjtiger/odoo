# -*- coding: utf-8 -*-
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
        self._gps(res_model='gps.owner.test', res_id=5, res_field='gps_id')
        with self.assertRaises(ValidationError):
            self._gps(res_model='gps.owner.test', res_id=5, res_field='gps_id')

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

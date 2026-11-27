# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDemoItemGps(TransactionCase):
    """ gps.mixin 在 mobile.demo.item 上的行为: 每个对象有自己的位置, 不共享 """

    def _gps(self, address="Somewhere"):
        return self.env['gps'].create({'address': address, 'latitude': 39.9, 'longitude': 116.4})

    def _age(self, gps):
        # 把位置的创建时间改到宽限期之前
        self.env.cr.execute("UPDATE gps SET create_date = %s WHERE id = %s",
                            (fields.Datetime.now().replace(year=2000), gps.id))

    def test_create_links_the_location_to_its_owner(self):
        gps = self._gps()
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': gps.id})
        self.assertEqual((gps.res_model, gps.res_id, gps.res_field), ('mobile.demo.item', item.id, 'gps_id'))

    def test_write_moves_the_owner_link_to_a_new_location(self):
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': self._gps().id})
        new_gps = self._gps("New place")
        item.write({'gps_id': new_gps.id})
        self.assertEqual((new_gps.res_model, new_gps.res_id), ('mobile.demo.item', item.id))

    def test_copy_gets_its_own_location(self):
        gps = self._gps()
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': gps.id})
        copy = item.copy({'name': "Copy"})
        self.assertNotEqual(copy.gps_id, gps)
        self.assertEqual(copy.gps_id.address, gps.address)
        self.assertEqual(copy.gps_id.res_id, copy.id)
        # 原记录的位置不受影响
        self.assertEqual(gps.res_id, item.id)

    def test_unlink_removes_only_its_own_location(self):
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': self._gps().id})
        other_gps = self._gps("Other")
        other = self.env['mobile.demo.item'].create({'name': "Other", 'gps_id': other_gps.id})
        own_gps = item.gps_id
        item.unlink()
        self.assertFalse(own_gps.exists())
        self.assertTrue(other_gps.exists())
        self.assertTrue(other.exists())

    def test_cron_keeps_an_old_location_its_owner_still_references(self):
        gps = self._gps()
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': gps.id})
        self._age(gps)
        self.env['gps']._cron_cleanup_orphans()
        self.assertTrue(gps.exists())
        self.assertEqual(item.gps_id, gps)

    def test_cron_removes_an_old_location_its_owner_no_longer_references(self):
        old_gps = self._gps("Old")
        item = self.env['mobile.demo.item'].create({'name': "Item", 'gps_id': old_gps.id})
        item.write({'gps_id': self._gps("New").id})
        self._age(old_gps)
        self.env['gps']._cron_cleanup_orphans()
        self.assertFalse(old_gps.exists())

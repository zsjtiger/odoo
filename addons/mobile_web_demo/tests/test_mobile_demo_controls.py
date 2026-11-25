# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDemoControls(TransactionCase):
    """ 控件演示字段: reference, float_toggle (factor), 明细的 handle 排序 """

    def test_reference_keeps_model_and_id(self):
        partner = self.env['res.partner'].create({'name': 'Ref partner'})
        item = self.env['mobile.demo.item'].create({'name': 'Ref item', 'ref_id': f'res.partner,{partner.id}'})
        self.assertEqual(item.ref_id, partner)

    def test_discount_is_stored_as_a_fraction(self):
        # float_toggle with factor 100 shows 10 for a stored 0.1
        item = self.env['mobile.demo.item'].create({'name': 'Discount item', 'discount': 0.1})
        self.assertAlmostEqual(item.discount * 100, 10.0)

    def test_lines_are_ordered_by_handle_sequence(self):
        item = self.env['mobile.demo.item'].create({'name': 'Ordered item'})
        second = self.env['mobile.demo.line'].create({'item_id': item.id, 'name': 'B', 'sequence': 20})
        first = self.env['mobile.demo.line'].create({'item_id': item.id, 'name': 'A', 'sequence': 10})
        # drop the cache filled at creation time, so the order comes from the database
        item.invalidate_recordset(['line_ids'])
        self.assertEqual(item.line_ids.ids, [first.id, second.id])

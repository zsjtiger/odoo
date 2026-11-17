# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPharaccountMobileWeb(TransactionCase):

    MOBILE_MENUS = [
        'menu_pharaccount_mobile_account',
        'menu_pharaccount_mobile_record_type',
        'menu_pharaccount_mobile_picklist',
        'menu_pharaccount_mobile_account_state',
    ]

    def test_mobile_menus_are_mobile_top_level_with_action(self):
        # The Mobile Web home grid only lists top-level menus that have an action.
        for xmlid in self.MOBILE_MENUS:
            menu = self.env.ref('pharaccount_mobile_web.' + xmlid)
            self.assertEqual(menu.device_type, 'mobile', xmlid)
            self.assertFalse(menu.parent_id, xmlid)
            self.assertTrue(menu.action, xmlid)

    def test_pc_menus_are_not_mobile_menus(self):
        # PC menus keep the default device_type, so the Mobile Web client does not show them.
        pc_root = self.env.ref('pharaccount.menu_pharaccount_pc_root')
        self.assertNotEqual(pc_root.device_type, 'mobile')

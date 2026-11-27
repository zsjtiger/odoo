# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudioMobile(TransactionCase):

    def test_mobile_infos_of_a_model(self):
        info = self.env['ir.model'].studio_mobile_infos('pharaccount.account')
        self.assertTrue(info['available'])
        self.assertTrue(info['icons'])
        self.assertTrue(info['pages'])
        self.assertEqual(set(info), {'available', 'model_id', 'action_id', 'menus', 'custom_fields',
                                     'nav_items', 'pages', 'icons'})
        self.assertTrue(all(menu['device_type'] in ('mobile', 'pc', 'both') for menu in info['menus']))

    def test_custom_field_is_listed(self):
        model = self.env['ir.model']._get('pharaccount.account')
        field = self.env['mobile.custom.field'].create({
            'name': 'State label', 'model_id': model.id, 'path': 'state_id.label',
        })
        info = self.env['ir.model'].studio_mobile_infos('pharaccount.account')
        self.assertIn(field.id, [cf['id'] for cf in info['custom_fields']])
        self.assertTrue(info['custom_fields'][0]['field_name'] or field.field_name)

    def test_model_without_action_has_no_navigation(self):
        info = self.env['ir.model'].studio_mobile_infos('res.partner.title')
        self.assertFalse(info['action_id'])
        self.assertFalse(info['nav_items'])

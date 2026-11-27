# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudioMobile(TransactionCase):

    def test_mobile_infos_of_a_model(self):
        info = self.env['ir.model'].studio_mobile_infos('pharaccount.account')
        self.assertTrue(info['available'])
        self.assertTrue(info['icons'])
        self.assertTrue(info['pages'])
        self.assertTrue({'available', 'model_id', 'action_id', 'mobile_action_id', 'menus', 'custom_fields',
                         'nav_items', 'pages', 'icons'} <= set(info))
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


@tagged('post_install', '-at_install')
class TestStudioFormViews(TransactionCase):

    def test_form_views_and_their_slots(self):
        info = self.env['ir.model'].studio_form_views('pharaccount.account')
        self.assertTrue(info['views'])
        self.assertTrue(info['mobile_action_id'])
        self.assertTrue(info['pc_action_id'])
        used = [label for view in info['views'] for label in view['used_by']]
        self.assertIn('mobile', used)
        self.assertIn('pc', used)

    def test_new_form_for_the_mobile_slot_replaces_the_mobile_form(self):
        model = self.env['ir.model']._get('pharaccount.account')
        before = self.env['ir.model'].studio_form_views('pharaccount.account')
        new_id = self.env['ir.model'].studio_create_form_view('pharaccount.account', 'Mobile test form', 'mobile')
        after = self.env['ir.model'].studio_form_views('pharaccount.account')
        new = next(v for v in after['views'] if v['id'] == new_id)
        self.assertIn('mobile', new['used_by'])
        # the previous mobile form is still there, but no longer used on mobile
        old_ids = [v['id'] for v in before['views'] if 'mobile' in v['used_by']]
        for old_id in old_ids:
            old = next(v for v in after['views'] if v['id'] == old_id)
            self.assertNotIn('mobile', old['used_by'])
        self.assertTrue(model)

    def test_new_form_for_a_record_type(self):
        hospital = self.env['ir.record.type'].search([('code', '=', 'hospital')])
        new_id = self.env['ir.model'].studio_create_form_view(
            'pharaccount.account', 'Hospital form', 'record_type', hospital.id)
        view = self.env['ir.ui.view'].browse(new_id)
        self.assertEqual(view.record_type_id, hospital)
        self.assertEqual(hospital.action_id.view_ids.filtered(lambda v: v.view_mode == 'form')[:1].view_id, view)

# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudioRecordTypes(TransactionCase):

    def test_infos_of_a_model_with_record_types(self):
        info = self.env['ir.model'].studio_record_type_infos('pharaccount.account')
        self.assertTrue(info['available'])
        self.assertTrue(info['declared'])
        codes = {rt['code'] for rt in info['types']}
        self.assertIn('hospital', codes)
        self.assertIn('pharma', codes)
        self.assertTrue(info['groups'])
        hospital = next(rt for rt in info['types'] if rt['code'] == 'hospital')
        perms = [p for p in info['permissions'] if p['record_type_id'] == hospital['id']]
        self.assertTrue(perms)
        self.assertTrue(all('allow_import' in p for p in perms))

    def test_infos_of_a_model_without_record_types(self):
        info = self.env['ir.model'].studio_record_type_infos('res.partner')
        self.assertTrue(info['available'])
        self.assertFalse(info['enabled'])
        self.assertFalse(info['types'])
        self.assertFalse(info['declared'])

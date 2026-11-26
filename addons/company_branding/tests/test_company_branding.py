# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompanyBranding(TransactionCase):

    def test_branding_defaults_are_empty_strings(self):
        company = self.env['res.company'].create({'name': 'Branding Test Co'})
        branding = company.with_company(company)._get_branding()
        self.assertEqual(branding['web_title'], '')
        self.assertEqual(branding['login_background_url'], '')

    def test_urls_must_be_http_or_https(self):
        company = self.env['res.company'].create({'name': 'Branding URL Co'})
        for value in ('javascript:alert(1)', 'data:image/png;base64,AAAA', 'https://'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                company.login_background_url = value
        company.login_background_url = 'https://example.com/bg.jpg'
        self.assertEqual(company.login_background_url, 'https://example.com/bg.jpg')

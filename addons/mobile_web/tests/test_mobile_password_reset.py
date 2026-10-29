# -*- coding: utf-8 -*-
import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMobilePasswordResetModel(TransactionCase):
    """ 找回密码的令牌: 创建、有效期、一次性使用、设置密码 """

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({'name': 'Reset User', 'login': 'reset_user@example.com'})
        self.Reset = self.env['mobile_web.password.reset']

    def test_token_is_created_for_an_active_user(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        self.assertTrue(reset)
        self.assertEqual(reset.user_id, self.user)
        self.assertGreater(len(reset.token), 30)

    def test_unknown_login_creates_no_token(self):
        self.assertFalse(self.Reset.create_for_login('nobody@example.com'))

    def test_valid_token_is_found(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        self.assertEqual(self.Reset.get_valid(reset.token), reset)

    def test_expired_token_is_rejected(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        reset.expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertFalse(self.Reset.get_valid(reset.token))

    def test_token_cannot_be_used_twice(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        reset.set_password('a-new-password-1')
        self.assertFalse(self.Reset.get_valid(reset.token))

    def test_unknown_or_empty_token_is_rejected(self):
        self.assertFalse(self.Reset.get_valid('not-a-token'))
        self.assertFalse(self.Reset.get_valid(False))

    def test_a_short_password_is_refused(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        with self.assertRaises(UserError):
            reset.set_password('short')
        self.assertFalse(reset.used)

    def test_a_valid_password_is_set_and_the_token_is_used(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        reset.set_password('a-long-new-password')
        self.assertTrue(reset.used)
        self.assertTrue(self.user.with_user(self.user)._check_credentials(
            {'type': 'password', 'password': 'a-long-new-password'}, {'interactive': True}))

    def test_delivery_sends_the_link_by_mail(self):
        reset = self.Reset.create_for_login('reset_user@example.com')
        reset.deliver()
        mail = self.env['mail.mail'].search([('email_to', '=', 'reset_user@example.com')])
        self.assertIn(reset.token, mail.body_html)


@tagged('post_install', '-at_install')
class TestMobilePasswordResetPages(HttpCase):
    """ 找回密码与设置新密码的页面 """

    def setUp(self):
        super().setUp()
        self.env['res.users'].create({'name': 'Page User', 'login': 'page_user@example.com'})

    def _post(self, form_path, path, data):
        """ 与浏览器一致: 先取得表单页面中的 csrf_token, 再提交 """
        html = self.url_open(form_path).text
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        return self.url_open(path, data=dict(data, csrf_token=token))

    def test_retrieve_page_renders(self):
        self.assertEqual(self.url_open('/mobile_web/retrieve_password').status_code, 200)

    def test_retrieve_says_the_link_is_sent_if_the_account_exists(self):
        response = self._post('/mobile_web/retrieve_password', '/mobile_web/retrieve_password',
                              {'login': 'page_user@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('If the account exists', response.text)

    def test_retrieve_gives_the_same_answer_for_unknown_accounts(self):
        known = self._post('/mobile_web/retrieve_password', '/mobile_web/retrieve_password',
                           {'login': 'page_user@example.com'}).text
        unknown = self._post('/mobile_web/retrieve_password', '/mobile_web/retrieve_password',
                             {'login': 'nobody@example.com'}).text
        self.assertEqual(known, unknown)

    def test_a_sent_link_is_reported_as_sent(self):
        with patch('odoo.addons.mobile_web.models.mobile_password_reset.MobilePasswordReset.deliver', return_value=True):
            response = self._post('/mobile_web/retrieve_password', '/mobile_web/retrieve_password',
                                  {'login': 'page_user@example.com'})
        self.assertIn('a reset link has been sent', response.text)

    def test_an_invalid_token_is_reported(self):
        response = self.url_open('/mobile_web/reset_password/not-a-token')
        self.assertIn('invalid or has expired', response.text)

    def test_a_valid_token_shows_the_form_and_sets_the_password(self):
        reset = self.env['mobile_web.password.reset'].sudo().create_for_login('page_user@example.com')
        response = self.url_open(f'/mobile_web/reset_password/{reset.token}')
        self.assertIn('Set new password', response.text)

        response = self._post(f'/mobile_web/reset_password/{reset.token}', f'/mobile_web/reset_password/{reset.token}',
                              {'password': 'a-long-new-password', 'confirm_password': 'a-long-new-password'})
        self.assertIn('Your password has been reset', response.text)
        self.assertFalse(self.env['mobile_web.password.reset'].sudo().get_valid(reset.token))

    def test_mismatched_passwords_are_refused(self):
        reset = self.env['mobile_web.password.reset'].sudo().create_for_login('page_user@example.com')
        response = self._post(f'/mobile_web/reset_password/{reset.token}', f'/mobile_web/reset_password/{reset.token}',
                              {'password': 'a-long-new-password', 'confirm_password': 'another-long-password'})
        self.assertIn('do not match', response.text)
        self.assertTrue(self.env['mobile_web.password.reset'].sudo().get_valid(reset.token))

    def test_a_wrong_password_on_login_shows_the_error(self):
        """ 回归测试: 登录页的错误提示此前因为使用了 t-esc 而不会显示 """
        response = self._post('/mobile_web/login', '/mobile_web/login',
                              {'login': 'page_user@example.com', 'password': 'wrong-password'})
        self.assertIn('Wrong login/password', response.text)

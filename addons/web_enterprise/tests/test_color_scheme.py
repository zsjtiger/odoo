# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import HttpCase, tagged
from odoo.addons.base.tests.common import new_test_user


@tagged('-at_install', 'post_install')
class TestColorScheme(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.default_user = new_test_user(cls.env, 'bob', groups='base.group_user', email='bob@test.com')
        cls.dark_user = new_test_user(cls.env, 'alice', groups='base.group_user', email='alice@test.com')
        cls.dark_user.res_users_settings_id.write({'color_scheme': 'dark'})

    def test_color_scheme_default(self):
        self.authenticate(self.default_user.login, self.default_user.login)
        response = self.url_open('/odoo')
        self.assertEqual(response.cookies.get('color_scheme'), 'light')

    def test_color_scheme_dark(self):
        self.authenticate(self.dark_user.login, self.dark_user.login)
        response = self.url_open('/odoo')
        self.assertEqual(response.cookies.get('color_scheme'), 'dark')

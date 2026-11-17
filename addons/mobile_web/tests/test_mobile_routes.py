# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMobileRoutes(HttpCase):
    """ 手机端的路由: 未登录跳转, 登录, 首页及其资源包, 菜单接口 """

    def test_anonymous_is_redirected_to_login(self):
        response = self.url_open('/mobile_web', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/mobile_web/login', response.headers['Location'])

    def test_login_then_home_and_menus(self):
        self.authenticate('admin', 'admin')
        home = self.url_open('/mobile_web')
        self.assertEqual(home.status_code, 200)
        self.assertIn('mobile_web.assets_backend', home.text)
        self.assertIn('mobile_web.assets_start', home.text)
        self.assertIn('odoo.__session_info__ =', home.text)

        menus = self.url_open('/mobile_web/webclient/load_menus/test')
        self.assertEqual(menus.status_code, 200)
        self.assertIsInstance(json.loads(menus.content), dict)

    def test_web_login_is_unchanged(self):
        """ 继承 web 的 Home 后, web 自己的登录路由仍然可用 """
        self.assertEqual(self.url_open('/web/login').status_code, 200)

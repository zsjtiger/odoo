# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMobileControllers(HttpCase):
    """ 手机端的 JSON/HTTP 接口: 搜索条件, 页面动作, 菜单按设备过滤 """

    def _json(self, path, params):
        response = self.url_open(path, data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params}),
                                 headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def test_search_domain_builds_ilike_on_rec_name(self):
        self.authenticate('admin', 'admin')
        rec_name = self.env['res.partner']._rec_name
        domain = self._json('/mobile_web/search_domain', {'model': 'res.partner', 'text': '  Ann  '})
        self.assertEqual(domain, [[rec_name, 'ilike', 'Ann']])

    def test_search_domain_empty_text_gives_no_condition(self):
        self.authenticate('admin', 'admin')
        self.assertEqual(self._json('/mobile_web/search_domain', {'model': 'res.partner', 'text': '   '}), [])

    def test_search_domain_unknown_model_gives_no_condition(self):
        self.authenticate('admin', 'admin')
        self.assertEqual(self._json('/mobile_web/search_domain', {'model': 'no.such.model', 'text': 'x'}), [])

    def test_search_domain_requires_login(self):
        response = self.url_open('/mobile_web/search_domain', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'params': {'model': 'res.partner', 'text': 'x'},
        }), headers={'Content-Type': 'application/json'})
        # 未登录时不能拿到搜索结果: 返回的可能是错误页或登录跳转, 但绝不是 JSON 的 result
        self.assertNotIn('"result"', response.text)

    def test_page_actions_load_returns_the_page_actions(self):
        self.authenticate('admin', 'admin')
        page = self.env['mobile_web.mobile.page'].create({'name': 'P', 'page_component_id': 'mobile_page.todo_page'})
        action = self.env['ir.actions.act_window'].create({'name': 'Partners', 'res_model': 'res.partner'})
        self.env['mobile_web.mobile.page.actions'].create({
            'name': 'Partners', 'mobile_page': page.id, 'ir_action': action.id,
            'svg_icon_href': '#crossnow-icon-TabHome',
        })
        result = self._json('/mobile_web/page_actions/load', {'mobile_page_id': page.id})
        self.assertEqual(result[0]['name'], 'Partners')
        self.assertEqual(result[0]['action_id'], action.id)

    def test_load_menus_only_returns_menus_for_mobile(self):
        """ 手机端的 load_menus 只包含 device_type 为 mobile 或 both 的菜单 """
        self.authenticate('admin', 'admin')
        # 菜单需要挂接动作才会出现在 load_menus 的结果中
        action = self.env['ir.actions.act_window'].sudo().create({'name': 'QA', 'res_model': 'res.partner'})
        menus = self.env['ir.ui.menu'].sudo()
        action_ref = f'ir.actions.act_window,{action.id}'
        mobile_menu = menus.create({'name': 'QA Mobile Only', 'device_type': 'mobile', 'action': action_ref})
        pc_menu = menus.create({'name': 'QA PC Only', 'device_type': 'pc', 'action': action_ref})
        response = self.url_open('/mobile_web/webclient/load_menus/test')
        self.assertEqual(response.status_code, 200)
        names = {menu['name'] for menu in json.loads(response.content).values()}
        self.assertIn(mobile_menu.name, names)
        self.assertNotIn(pc_menu.name, names)

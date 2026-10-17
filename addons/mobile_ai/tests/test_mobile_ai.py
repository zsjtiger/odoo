# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.mobile_web.models.mobile_page import PAGE_COMPONENT_IDS


@tagged('post_install', '-at_install')
class TestMobileAI(TransactionCase):
    """ 移动端 AI 入口: 页面组件与标签栏配置 """

    def test_ai_page_has_a_frontend_component(self):
        page = self.env.ref('mobile_ai.ai_page')
        self.assertIn(page.page_component_id, PAGE_COMPONENT_IDS)

    def test_ai_is_in_every_tab_bar(self):
        """ 安装本模块后, 首页、待办、日程、我的 的标签栏都有 AI 入口 """
        ai_action = self.env.ref('mobile_ai.ai_page_action')
        for xmlid in ('home_page', 'todo_page', 'schedule_page', 'user_my_page'):
            with self.subTest(page=xmlid):
                page = self.env.ref(f'mobile_web.{xmlid}')
                tab = self.env['mobile_web.mobile.page.actions'].search([
                    ('mobile_page', '=', page.id),
                    ('ir_action', '=', ai_action.id),
                ])
                self.assertEqual(len(tab), 1)
                self.assertTrue(tab.svg_icon_href)

    def test_ai_page_has_its_own_tab_bar(self):
        page = self.env.ref('mobile_ai.ai_page')
        tabs = self.env['mobile_web.mobile.page.actions'].search([('mobile_page', '=', page.id)])
        self.assertEqual(len(tabs), 5)

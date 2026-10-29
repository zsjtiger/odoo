# -*- coding: utf-8 -*-
import re
from pathlib import Path

from odoo.tests import TransactionCase

from ..models.mobile_page import PAGE_COMPONENT_IDS, get_sprite_icon_ids

PAGE_KEYS_JS = Path(__file__).resolve().parents[1] / 'static' / 'src' / 'pages' / 'shared' / 'page_keys.js'


class TestMobilePage(TransactionCase):

    def test_frontend_keys_match_backend_list(self):
        """ 前端注册的页面key必须与后端列表完全一致 """
        js_keys = set(re.findall(r'"(mobile_page\.[a-z_]+)"', PAGE_KEYS_JS.read_text(encoding='utf-8')))
        self.assertEqual(js_keys, set(PAGE_COMPONENT_IDS))

    def test_configured_pages_have_a_frontend_component(self):
        """ 数据中配置的页面都必须有对应的前端组件 """
        for page in self.env['mobile_web.mobile.page'].search([]):
            with self.subTest(page=page.name):
                self.assertIn(page.page_component_id, PAGE_COMPONENT_IDS)

    def test_configured_icons_are_in_the_sprite(self):
        """ 数据中配置的导航图标都必须在精简后的图标雪碧图中 """
        sprite_ids = get_sprite_icon_ids()
        for action in self.env['mobile_web.mobile.page.actions'].search([('svg_icon_href', '!=', False)]):
            with self.subTest(icon=action.svg_icon_href):
                self.assertIn(action.svg_icon_href.lstrip('#'), sprite_ids)

# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from ..models.mobile_page import get_sprite_icon_ids


@tagged('post_install', '-at_install')
class TestMobileModels(TransactionCase):
    """ 手机端的模型: 页面导航动作, 动作绑定页面的读取, 图标雪碧图 """

    def setUp(self):
        super().setUp()
        self.page = self.env['mobile_web.mobile.page'].create({
            'name': 'Test Home',
            'page_component_id': 'mobile_page.home_page',
        })

    def test_page_actions_are_ordered_by_sequence(self):
        action_b = self.env['ir.actions.act_window'].create({'name': 'B', 'res_model': 'res.partner'})
        action_a = self.env['ir.actions.act_window'].create({'name': 'A', 'res_model': 'res.partner'})
        self.env['mobile_web.mobile.page.actions'].create([
            {'name': 'Second', 'mobile_page': self.page.id, 'ir_action': action_b.id, 'sequence': 20,
             'svg_icon_href': '#crossnow-icon-TabMy'},
            {'name': 'First', 'mobile_page': self.page.id, 'ir_action': action_a.id, 'sequence': 10,
             'svg_icon_href': '#crossnow-icon-TabHome'},
        ])
        actions = self.env['mobile_web.mobile.page.actions'].get_page_actions(self.page.id)
        self.assertEqual([a['name'] for a in actions], ['First', 'Second'])
        self.assertEqual(actions[0]['action_id'], action_a.id)
        self.assertEqual(actions[0]['svg_icon_href'], '#crossnow-icon-TabHome')

    def test_page_actions_of_other_pages_are_not_returned(self):
        other = self.env['mobile_web.mobile.page'].create({
            'name': 'Other', 'page_component_id': 'mobile_page.todo_page',
        })
        action = self.env['ir.actions.act_window'].create({'name': 'X', 'res_model': 'res.partner'})
        self.env['mobile_web.mobile.page.actions'].create({
            'name': 'Only other', 'mobile_page': other.id, 'ir_action': action.id,
        })
        self.assertEqual(self.env['mobile_web.mobile.page.actions'].get_page_actions(self.page.id), [])

    def test_mobile_page_action_reads_its_binding_as_a_tuple(self):
        action = self.env['ir.actions.mobile_page'].create({
            'name': 'Home',
            'type': 'ir.actions.mobile_page',
            'binding_mobile_page': self.page.id,
        })
        value = action.read(['binding_mobile_page'])[0]['binding_mobile_page']
        self.assertEqual(value, (self.page.id, self.page.display_name, 'mobile_page.home_page'))

    def test_mobile_page_action_without_binding_reads_false(self):
        action = self.env['ir.actions.mobile_page'].create({'name': 'Unbound', 'type': 'ir.actions.mobile_page'})
        value = action.read(['binding_mobile_page'])[0]['binding_mobile_page']
        self.assertFalse(value)

    def test_icon_sprite_contains_the_icons_used_by_the_pages(self):
        sprite_ids = get_sprite_icon_ids()
        for icon in ['crossnow-icon-TabHome', 'crossnow-icon-TabMy',
                     'crossnow-icon-TabSchedule', 'crossnow-icon-TabWaiting']:
            self.assertIn(icon, sprite_ids)

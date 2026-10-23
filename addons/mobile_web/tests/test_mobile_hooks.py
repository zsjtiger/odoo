# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMobileHooks(TransactionCase):
    """ 安装/卸载钩子: 表结构可重复执行, 缺失的页面组件与图标只记录警告 """

    def test_pre_init_hook_can_run_twice(self):
        from .. import _post_init_hook, _pre_init_hook, _uninstall_hook  # noqa: PLC0415
        _pre_init_hook(self.env)
        _pre_init_hook(self.env)
        self.env.cr.execute("SELECT to_regclass('ir_act_mobile_page')")
        self.assertTrue(self.env.cr.fetchone()[0])

    def test_post_init_hook_warns_about_unknown_page_component(self):
        from .. import _post_init_hook, _pre_init_hook, _uninstall_hook  # noqa: PLC0415
        self.env['mobile_web.mobile.page'].create({'name': 'Broken', 'page_component_id': 'mobile_page.nope'})
        with self.assertLogs('odoo.addons.mobile_web', level='WARNING') as logs:
            _post_init_hook(self.env)
        self.assertTrue(any('mobile_page.nope' in line for line in logs.output))

    def test_post_init_hook_warns_about_icon_missing_from_the_sprite(self):
        from .. import _post_init_hook, _pre_init_hook, _uninstall_hook  # noqa: PLC0415
        page = self.env['mobile_web.mobile.page'].create({
            'name': 'Icon page', 'page_component_id': 'mobile_page.home_page',
        })
        action = self.env['ir.actions.act_window'].create({'name': 'I', 'res_model': 'res.partner'})
        self.env['mobile_web.mobile.page.actions'].create({
            'name': 'I', 'mobile_page': page.id, 'ir_action': action.id,
            'svg_icon_href': '#crossnow-icon-DoesNotExist',
        })
        with self.assertLogs('odoo.addons.mobile_web', level='WARNING') as logs:
            _post_init_hook(self.env)
        self.assertTrue(any('crossnow-icon-DoesNotExist' in line for line in logs.output))

    def test_post_init_hook_is_quiet_for_valid_data(self):
        from .. import _post_init_hook, _pre_init_hook, _uninstall_hook  # noqa: PLC0415
        page = self.env['mobile_web.mobile.page'].create({
            'name': 'Valid page', 'page_component_id': 'mobile_page.home_page',
        })
        action = self.env['ir.actions.act_window'].create({'name': 'V', 'res_model': 'res.partner'})
        self.env['mobile_web.mobile.page.actions'].create({
            'name': 'V', 'mobile_page': page.id, 'ir_action': action.id,
            'svg_icon_href': '#crossnow-icon-TabHome',
        })
        # 没有警告时 assertNoLogs 应通过
        with self.assertNoLogs('odoo.addons.mobile_web', level='WARNING'):
            _post_init_hook(self.env)

    def test_uninstall_hook_drops_the_inherited_table_and_pre_init_restores_it(self):
        from .. import _post_init_hook, _pre_init_hook, _uninstall_hook  # noqa: PLC0415
        _uninstall_hook(self.env)
        self.env.cr.execute("SELECT to_regclass('ir_act_mobile_page')")
        self.assertFalse(self.env.cr.fetchone()[0])
        _pre_init_hook(self.env)
        self.env.cr.execute("SELECT to_regclass('ir_act_mobile_page')")
        self.assertTrue(self.env.cr.fetchone()[0])

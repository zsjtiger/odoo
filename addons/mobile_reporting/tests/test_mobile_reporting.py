# -*- coding: utf-8 -*-
from lxml import etree

from odoo.tests import TransactionCase, tagged

CHART_FIELDS = {
    'chart_bar', 'chart_line', 'chart_pie', 'chart_gauge', 'chart_radar', 'chart_card',
    'chart_smooth', 'chart_stacked', 'chart_marked', 'chart_pie_line', 'chart_polar_radial',
    'chart_polar_tangential', 'chart_polar_end_angle', 'chart_bar_horizontal',
    'chart_bar_axis_break', 'chart_bar_gradient',
    'chart_doughnut',
    'chart_doughnut_rounded',
    'chart_doughnut_half',
    'chart_pie_pad',
    'chart_scatter',
    'chart_scatter_quartet',
    'chart_scatter_cluster',
    'chart_scatter_cluster_process',
    'chart_scatter_regression',
    'chart_scatter_effect',
}


@tagged('post_install', '-at_install')
class TestMobileReporting(TransactionCase):

    def test_action_lists_the_reports_and_opens_the_mobile_form(self):
        action = self.env.ref('mobile_reporting.mobile_reporting_demo_action')
        self.assertEqual(action.res_model, 'reporting.demo')
        self.assertEqual(action.view_mode, 'list,form')
        self.assertEqual(action.view_id, self.env.ref('mobile_reporting.mobile_reporting_demo_list'))
        form_binding = action.view_ids.filtered(lambda v: v.view_mode == 'form')
        self.assertEqual(form_binding.view_id, self.env.ref('mobile_reporting.mobile_reporting_demo_form'))

    def test_mobile_form_shows_every_chart_with_the_reporting_widget(self):
        view = self.env.ref('mobile_reporting.mobile_reporting_demo_form')
        fields = etree.fromstring(view.arch).xpath('//field')
        self.assertEqual({f.get('name') for f in fields}, CHART_FIELDS)
        for field in fields:
            self.assertTrue(field.get('widget', '').startswith('board_dashboard_'))

    def test_desktop_form_is_not_replaced(self):
        # 桌面端的表单视图优先级更高(数值更小), 移动端视图不能成为默认表单
        default_form = self.env['reporting.demo'].get_view(view_type='form')
        self.assertNotEqual(default_form['id'], self.env.ref('mobile_reporting.mobile_reporting_demo_form').id)

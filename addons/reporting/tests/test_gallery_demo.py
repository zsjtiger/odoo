# -*- coding: utf-8 -*-
import json

from lxml import etree

from odoo.tests import TransactionCase, tagged

GALLERY = {
    'chart_smooth': 'board_dashboard_smooth_line',
    'chart_stacked': 'board_dashboard_stacked_line',
    'chart_marked': 'board_dashboard_marked_line',
    'chart_pie_line': 'board_dashboard_pie_line',
    'chart_polar_radial': 'board_dashboard_polar_radial',
    'chart_polar_tangential': 'board_dashboard_polar_tangential',
    'chart_polar_end_angle': 'board_dashboard_polar_end_angle',
    'chart_bar_horizontal': 'board_dashboard_bar_horizontal',
    'chart_bar_axis_break': 'board_dashboard_bar_axis_break',
    'chart_bar_gradient': 'board_dashboard_bar_gradient',
}


@tagged('post_install', '-at_install')
class TestGalleryDemo(TransactionCase):

    def test_every_gallery_chart_has_demo_data_in_its_own_field(self):
        record = self.env.ref('reporting.board_demo_record')
        for field, _widget in GALLERY.items():
            rows = json.loads(record[field])
            self.assertTrue(rows, field)
            for row in rows:
                self.assertEqual(set(row), {'name', 'value', 'category', 'filter_domain'}, field)

    def test_every_gallery_chart_has_a_form_with_its_widget(self):
        for field, widget in GALLERY.items():
            view = self.env.ref('reporting.board_demo_view_%s' % field.replace('chart_', ''))
            found = etree.fromstring(view.arch).xpath('//field[@name=$name]', name=field)
            self.assertEqual(len(found), 1, field)
            self.assertEqual(found[0].get('widget'), widget)

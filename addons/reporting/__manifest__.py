# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# pylint: disable=W0104
# W0104是Statement seems to have no effect错误，__manifest__.py仅是一个字典定义
{
    'name': 'Dashboards',
    'version': '1.0',
    'category': 'Productivity',
    'sequence': 225,
    'summary': 'Build your own dashboards',
    'description': """
    """,
    'depends': ['base', 'web'],
    'data': [
        'security/ir.access.csv',
        'data/board_demo.xml',
        'views/board_views.xml',
        'views/board_demo_views.xml',
    ],
    'application': True,
    'assets': {
        'web.assets_backend': [
            # echarts 必须先于图表部件加载
            'reporting/static/lib/echarts.min.js',
            'reporting/static/src/**/*.scss',
            'reporting/static/src/**/*.js',
        ],
        'web.assets_unit_tests': [
            'reporting/static/lib/echarts.min.js',
            'reporting/static/tests/**/*.test.js',
        ],
    },
    'license': 'LGPL-3',
}

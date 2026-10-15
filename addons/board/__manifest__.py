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
        'views/board_views.xml',
    ],
    'application': True,
    'assets': {
        'web.assets_backend': [
            # echarts 必须先于图表部件加载
            'board/static/lib/echarts.min.js',
            'board/static/src/**/*.scss',
            'board/static/src/**/*.js',
            'board/static/src/**/*.xml',
        ],
        'web.assets_unit_tests': [
            'board/static/lib/echarts.min.js',
            'board/static/tests/**/*.test.js',
        ],
    },
    'license': 'LGPL-3',
}

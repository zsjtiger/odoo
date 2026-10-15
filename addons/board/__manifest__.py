# -*- coding: utf-8 -*-
# Part of Crossnow. See LICENSE file for full copyright and licensing details.
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
        'security/ir.model.access.csv',
        'views/webclient_templates.xml',
    ],
    'application': True,
    'assets': {
        'web.assets_backend': [
            'board/static/src/**/*.scss',
            'board/static/src/**/*.js',
        ],
        'web.assets_qweb': [
            'board/static/src/**/*.xml',
        ],
    },
    'license': 'LGPL-3',
}

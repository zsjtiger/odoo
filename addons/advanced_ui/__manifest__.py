# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': "Advanced UI",
    'summary': "Advanced user interface features",
    'description': """
Advanced UI
===========

Advanced features of the user interface, built on top of the web client.
""",
    'category': 'Hidden',
    'version': '1.0',
    'depends': ['web'],
    'data': [
        'data/search_tree_demo.xml',
        'views/datatable_demo_views.xml',
        'views/search_tree_demo_views.xml',
        'views/tree_form_demo_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'advanced_ui/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'advanced_ui/static/tests/**/*',
        ],
    },
}

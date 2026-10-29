# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': "Website Studio",
    'summary': "Display Website Elements in Studio",
    'description': """
Studio - Customize Odoo
=======================

This addon allows the user to display all the website forms linked to a certain
model. Furthermore, you can create a new website form or edit an existing one.

""",
    'category': 'Hidden',
    'depends': [
        'web_builder',
        'website',
    ],
    'data': [
        'views/templates.xml',
        'views/views.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'assets': {
        'web_builder.studio_assets_minimal': [
            'website_builder/static/src/editor_tabs.js',
        ],
        'web.assets_tests': [
            'website_builder/static/tests/tours/**/*',
        ],
        'web.assets_unit_tests': [
            'website_builder/static/tests/builder/**/*',
        ],
        'website.website_builder_assets': [
            'website_builder/static/src/plugins/**/*',
        ],
    }
}

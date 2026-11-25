# -*- coding: utf-8 -*-
{
    'name': 'Mobile Web Theme',
    'version': '20.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Colors and style tokens of the Mobile Web client',
    'description': """
Mobile Web Theme
================

Sets the colors and style tokens of the Mobile Web client. The values are in
``static/src/scss/theme.scss``; they are loaded before the Mobile Web styles and
override the defaults in ``mobile_web/static/src/styles/00_tokens.scss``.

Change a value there and upgrade the module (or restart with asset regeneration)
to see the new colors. Scripts read the palettes from CSS variables, so they follow
the theme too.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['mobile_web'],
    'assets': {
        # prepended: the theme values must be defined before the tokens file uses them
        'mobile_web.assets_backend': [
            ('prepend', 'mobile_web_theme/static/src/scss/theme.scss'),
        ],
        'mobile_web.assets_frontend': [
            ('prepend', 'mobile_web_theme/static/src/scss/theme.scss'),
        ],
        # desktop web: core Bootstrap and Odoo brand variables mapped from the same palette
        'web.assets_backend': [
            ('prepend', 'mobile_web_theme/static/src/scss/web_theme.scss'),
        ],
        # login, portal and website pages
        'web.assets_frontend': [
            ('prepend', 'mobile_web_theme/static/src/scss/web_theme.scss'),
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

# -*- coding: utf-8 -*-
{
    'name': 'Company Branding',
    'version': '20.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Web and mobile title, icon, logo and login background from URLs, set per company',
    'description': """
Company Branding
================

Configure on the company form, for the web client and the mobile web client:

* title (browser tab title)
* icon (browser tab icon)
* logo (shown on the login page)
* login background image

All images are URLs (http or https). Nothing is uploaded to the database.
The values are read by ``/company_branding/config`` and applied in the browser.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mobile_web'],
    'data': [
        'views/res_company_views.xml',
    ],
    'assets': {
        'web.assets_frontend': ['company_branding/static/src/js/branding.js'],
        'web.assets_backend': ['company_branding/static/src/js/branding.js'],
        'mobile_web.assets_frontend': ['company_branding/static/src/js/branding.js'],
        'mobile_web.assets_backend': ['company_branding/static/src/js/branding.js'],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

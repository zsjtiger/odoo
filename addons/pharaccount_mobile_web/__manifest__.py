# -*- coding: utf-8 -*-
{
    'name': 'Pharmacy Account - Mobile Web',
    'version': '20.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Pharmacy account screens and configuration in the Odoo Mobile Web client',
    'description': """
Pharmacy account in Mobile Web
==============================

Shows the pharmacy account screens and the configuration screens (record types,
picklists, account states) in the Mobile Web client, at /mobile_web.

The menus here have ``device_type = 'mobile'``, so the Mobile Web client shows them
and the PC client does not. The actions and views are defined in ``pharaccount``.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['pharaccount', 'mobile_web'],
    'data': [
        'data/pharaccount_mobile_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

# -*- coding: utf-8 -*-
{
    'name': "Mobile Web Demo",
    'category': 'Hidden',
    'summary': "Demo model and views that exercise every mobile list and form control",
    'description': """
Mobile Web Demo
===============

A test model covering the field types, widgets and view attributes that the
mobile web client supports: list marks (mobile_title / mobile_badge /
mobile_subtitle / mobile_date, sortable / filterable, default_order), and form
layout (groups, separators, notebook, one2many, required / readonly / invisible).
    """,
    'version': '1.0',
    'depends': ['mobile_web'],
    'data': [
        'security/ir.access.csv',
        'views/mobile_demo_views.xml',
        'data/mobile_demo_data.xml',
    ],
    'license': 'LGPL-3',
    'application': False,
}

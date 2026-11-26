# -*- coding: utf-8 -*-
{
    'name': 'Record Types',
    'version': '20.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Generic record types for any model: per-type access, rules, defaults and menus',
    'description': """
Record Types
============

Models opt in to record types (``ir.model`` flag). A record type is metadata of its
model, configured the same way as the model itself:

* access rows and record rules scoped to the type (``ir.access``)
* per-group permissions (``ir.record.type.permission``) generated into ``ir.access``
* per-group default type (``ir.record.type.default``)
* a menu and window action per type

See ``doc/design.md`` for the design.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.access.csv',
        'views/ir_record_type_views.xml',
        'views/ir_model_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

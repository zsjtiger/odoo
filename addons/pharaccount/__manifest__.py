# -*- coding: utf-8 -*-
{
    'name': 'Pharmacy Account',
    'version': '20.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Pharmacy accounts with record types, picklists and group permissions',
    'description': """
Pharmacy account (pharaccount)
==============================

First version, following vrux:

* Record types with inheritance (parent ``pharma``, children chain head,
  chain branch and monomer). The groups and picklist values of a child are
  the union of its own and its parent's.
* Picklists (``pharmacy_level``) shown by a standalone control, and limited
  per group.
* Pharmacy account main table with self references and picklist references.
* Permissions by group. A user can belong to several groups.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/pharaccount_security.xml',
        'security/ir.access.csv',
        'data/pharaccount_data.xml',
        'views/pharaccount_views.xml',
        'views/pharaccount_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

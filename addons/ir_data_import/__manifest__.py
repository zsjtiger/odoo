# -*- coding: utf-8 -*-
{
    'name': 'Data Import',
    'version': '20.0.1.1.0',
    'category': 'Technical',
    'summary': 'Import records from Excel templates with New / Update / Delete actions and row validation',
    'description': """
Data Import
===========

* Import button on a model (opt-in per model and group).
* Excel template per model, or per record type, with configurable columns and styles.
* Action column: N (new), U (update by ID), D (delete by ID).
* Row validation in a savepoint per row; errors are written to a Validation Error column of the
  result file. Nothing is saved while validating, and an import is all-or-nothing.
* Declarative rules (domain + message) and Python hooks (_import_validate_row) for custom checks.
    """,
    'author': 'pharaccount',
    'license': 'LGPL-3',
    'depends': ['base', 'ir_recordtype'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/ir.access.csv',
        'views/ir_data_import_views.xml',
        'views/ir_data_import_menus.xml',
        'wizard/ir_data_import_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

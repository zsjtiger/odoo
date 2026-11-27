# -*- coding: utf-8 -*-
"""Remove the legacy pharaccount.record.type model after its data moved to ir.record.type.

Runs after the models and data are loaded, so the framework types and their picklist
relation already exist. Steps:
1. copy the legacy picklist limits to the framework types;
2. remove the legacy actions, menu and views (through the ORM, so their metadata goes too);
3. drop the legacy column on accounts and the legacy tables;
4. remove the legacy model metadata.
"""
from odoo import SUPERUSER_ID, api

LEGACY_RECORDS = [
    ('ir.actions.act_window', 'action_pharaccount_record_type'),
    ('ir.actions.act_window', 'action_pharaccount_record_type_mobile'),
    ('ir.ui.menu', 'menu_pharaccount_pc_record_type'),
    ('ir.ui.view', 'view_pharaccount_record_type_list'),
    ('ir.ui.view', 'view_pharaccount_record_type_form'),
    ('ir.ui.view', 'view_pharaccount_record_type_kanban_mobile'),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("SELECT to_regclass('pharaccount_record_type_picklist_value_rel')")
    if cr.fetchone()[0]:
        cr.execute("""
            INSERT INTO pharaccount_ir_record_type_picklist_value_rel (record_type_id, value_id)
            SELECT l.ir_record_type_id, r.value_id
              FROM pharaccount_record_type_picklist_value_rel r
              JOIN pharaccount_record_type l ON l.id = r.record_type_id
             WHERE l.ir_record_type_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)

    for model, xmlid in LEGACY_RECORDS:
        record = env.ref(f'pharaccount.{xmlid}', raise_if_not_found=False)
        if record:
            record.unlink()

    cr.execute("ALTER TABLE pharaccount_account DROP COLUMN IF EXISTS legacy_record_type_id")
    cr.execute("""
        DROP TABLE IF EXISTS pharaccount_record_type_picklist_value_rel,
                             pharaccount_record_type_group_rel,
                             pharaccount_record_type CASCADE
    """)
    cr.execute("DELETE FROM ir_model_data WHERE module = 'pharaccount' AND model = 'pharaccount.record.type'")
    cr.execute("DELETE FROM ir_model WHERE model = 'pharaccount.record.type'")

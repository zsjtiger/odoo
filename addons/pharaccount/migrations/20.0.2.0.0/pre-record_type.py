# -*- coding: utf-8 -*-
"""Before the models load: free the record_type_id name and reset this module's access rows.

The framework field record_type_id (ir.record.type) replaces the legacy many2one to
pharaccount.record.type, so the old column is renamed. The access rows of this module
are dropped; security/ir.access.csv reloads them with the record-type scoping.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'pharaccount_account' AND column_name = 'record_type_id'
    """)
    if cr.fetchone():
        cr.execute("ALTER TABLE pharaccount_account RENAME COLUMN record_type_id TO legacy_record_type_id")
    cr.execute("""
        DELETE FROM ir_access WHERE id IN (
            SELECT res_id FROM ir_model_data WHERE module = 'pharaccount' AND model = 'ir.access')
    """)
    cr.execute("DELETE FROM ir_model_data WHERE module = 'pharaccount' AND model = 'ir.access'")

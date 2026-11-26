# -*- coding: utf-8 -*-
"""perm_import is renamed to allow_import (same name on every import permission level)."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ir_data_import_permission' AND column_name = 'perm_import'
    """)
    if cr.fetchone():
        cr.execute("ALTER TABLE ir_data_import_permission RENAME COLUMN perm_import TO allow_import")

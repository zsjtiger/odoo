# -*- coding: utf-8 -*-
"""Move the record type menus (hospital, doctor, pharmacy) under the master data menu."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.record.type']._pharaccount_create_default_types()

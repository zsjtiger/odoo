# -*- coding: utf-8 -*-
"""After the data is loaded: mirror the legacy record types and enable record types on accounts."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['pharaccount.record.type']._sync_to_record_types()

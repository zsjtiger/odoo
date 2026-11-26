# -*- coding: utf-8 -*-
"""Show the pharmacy record types under the pharmacy root and grant the pharmacy type to the groups."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.record.type']._pharaccount_create_default_types()

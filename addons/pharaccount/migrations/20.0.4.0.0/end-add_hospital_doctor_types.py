# -*- coding: utf-8 -*-
"""Add the hospital and doctor record types of the shared account model (with default access)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.record.type']._pharaccount_create_default_types()

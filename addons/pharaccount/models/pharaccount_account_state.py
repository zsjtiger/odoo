# -*- coding: utf-8 -*-
from odoo import fields, models


class PharaccountAccountState(models.Model):
    """Status of a pharmacy account. Mirrors vrux ``object_states`` for accounts."""
    _name = 'pharaccount.account.state'
    _description = 'Pharmacy Account State'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    label = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    color = fields.Char()
    is_default = fields.Boolean(string='Default')
    is_locked = fields.Boolean(string='Locked', help='A locked account cannot be edited.')
    description = fields.Char()

    _name_unique = models.Constraint('UNIQUE(name)', 'The state code must be unique.')

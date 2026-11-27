# -*- coding: utf-8 -*-
import ast

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class IrDataImportRule(models.Model):
    """Declarative row check: a row must match the domain, otherwise the message is reported."""
    _name = 'ir.data.import.rule'
    _description = 'Data Import Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    record_type_id = fields.Many2one('ir.record.type', string='Record Type', ondelete='cascade',
                                     domain="[('model_id', '=', model_id)]")
    action = fields.Selection([
        ('all', 'All actions'), ('N', 'New'), ('U', 'Update'),
    ], default='all', required=True, help='Delete rows are not checked by rules.')
    domain = fields.Char(default='[]', required=True,
                         help='Condition every imported row must satisfy, for example [("email", "!=", False)].')
    message = fields.Char(required=True, help='Reported in Validation Error when the row does not match.')

    @api.constrains('domain')
    def _check_domain(self):
        for rule in self:
            try:
                parsed = ast.literal_eval(rule.domain or '[]')
            except (ValueError, SyntaxError) as exc:
                raise ValidationError(_('The domain must be a literal list: %s', exc)) from exc
            if not isinstance(parsed, list):
                raise ValidationError(_('The domain must be a list.'))

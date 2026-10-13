"""The client actions (ir.actions.client)."""

from __future__ import annotations

from odoo import api, fields, models
from odoo.tools.safe_eval import expr_eval


class IrActionsClient(models.Model):
    _name = 'ir.actions.client'
    _description = 'Client Action'
    _inherit = ['ir.actions.actions']
    _table = 'ir_act_client'
    _order = 'name, id'
    _allow_sudo_commands = False

    type = fields.Char(default='ir.actions.client')

    tag = fields.Char(string='Client action tag', required=True,
                      help="An arbitrary string, interpreted by the client"
                           " according to its own needs and wishes. There "
                           "is no central tag repository across clients.")
    target = fields.Selection([('current', 'Current Window'), ('new', 'New Window'), ('fullscreen', 'Full Screen'), ('main', 'Main action of Current Window')], default="current", string='Target Window')
    res_model = fields.Char(string='Destination Model', help="Optional model, mostly used for needactions.")
    context = fields.Char(string='Context Value', default="{}", required=True, help="Context dictionary as Python expression, empty by default (Default: {})")
    params = fields.Json(
        compute='_compute_params', inverse='_inverse_params', string='Supplementary arguments',
        help="Arguments sent to the client along with the view tag")
    params_store = fields.Text(string='Params storage', readonly=True)

    @api.depends('params_store')
    def _compute_params(self):
        for record in self:
            record.params = record.params_store and expr_eval(record.params_store, {'uid': self.env.uid})

    def _inverse_params(self):
        for record in self:
            params = record.params
            record.params_store = repr(params) if isinstance(params, dict) else params

    def _get_readable_fields(self):
        return super()._get_readable_fields() | {
            "context", "params", "res_model", "tag", "target",
        }

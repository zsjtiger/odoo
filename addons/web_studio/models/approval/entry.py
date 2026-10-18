# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models, fields, _


class StudioApprovalEntry(models.Model):
    _name = 'studio.approval.entry'
    _description = 'Studio Approval Entry'
    # entries don't have the studio mixin since they depend on the data of the
    # db - they cannot be included into the Studio Customizations module

    @api.model
    def _default_user_id(self):
        return self.env.user

    name = fields.Char(compute='_compute_name', store=True)
    user_id = fields.Many2one('res.users', string='Approved/rejected by', ondelete='restrict',
                              required=True, default=lambda s: s._default_user_id(), index=True)
    # cascade deletion from the rule should only happen when the model itself is deleted
    rule_id = fields.Many2one('studio.approval.rule', string='Rule', ondelete='cascade',
                              required=True, index=True)
    # store these for performance reasons, reading should be fast while writing can be slower
    model = fields.Char(string='Model Name', related="rule_id.model_name", store=True)
    method = fields.Char(string='Method', related="rule_id.method", store=True)
    action_id = fields.Many2one('ir.actions.actions', related="rule_id.action_id", store=True)
    res_id = fields.Many2oneReference(string='Record ID', model_field='model', required=True)
    reference = fields.Char(string='Reference', compute='_compute_reference')
    approved = fields.Boolean(string='Approved')
    record_display_name = fields.Char(string='Record', compute='_compute_record')
    state = fields.Selection(selection=[
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='State',
        compute='_compute_state',
    )

    _uniq_combination = models.Constraint(
        'unique(rule_id,model,res_id)',
        "A rule can only be approved/rejected once per record.",
    )
    _model_res_id_idx = models.Index("(model, res_id)")

    @api.depends('model', 'res_id')
    def _compute_record(self):
        recs = {}
        for model, entries in self.grouped('model').items():
            records = self.env[model].browse(entries.mapped('res_id'))
            recs.update({(model, record.id): record.display_name for record in records})

        for entry in self:
            if not entry.id:
                entry.record_display_name = None
            else:
                entry.record_display_name = recs[entry.model, entry.res_id]

    @api.depends('record_display_name', 'rule_id')
    def _compute_name(self):
        notification_order_selection = dict(self.env['studio.approval.rule']._fields['notification_order']._description_selection(self.env))

        for entry in self:
            if not entry.id:
                entry.name = _('New Approval Entry')
            else:
                entry.name = '%s - %s' % (entry.record_display_name, notification_order_selection.get(entry.rule_id.notification_order, entry.rule_id.notification_order))

    @api.depends('model', 'res_id')
    def _compute_reference(self):
        for entry in self:
            entry.reference = "%s,%s" % (entry.model, entry.res_id)

    @api.depends('approved')
    def _compute_state(self):
        for entry in self:
            entry.state = 'approved' if entry.approved else 'rejected'

    def action_show_model(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'res_model': self.model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        entries = super().create(vals_list)
        entries._notify_approval()
        return entries

    def _delete_entries(self, records):
        model_name = records._name
        existing_entries = self.sudo().env['studio.approval.entry'].search([
            ('model', '=', model_name),
            ('res_id', 'in', records.ids)
        ])
        existing_entries.unlink()

    def write(self, vals):
        res = super().write(vals)
        self._notify_approval()
        return res

    def _notify_approval(self):
        """Post a generic note on the record if it inherits mail.thread."""
        for entry in self:
            if not entry.rule_id.model_id.is_mail_thread:
                continue
            record = self.env[entry.model].browse(entry.res_id)
            partner_ids = entry.rule_id.users_to_notify.partner_id
            rule = entry.rule_id
            target_name = ""
            if rule.name:
                target_name = rule.name
            elif rule.method:
                target_name = _("Method: %s", rule.method)
            elif rule.action_id.name:
                target_name = _("Action: %s", rule.action_id.name)

            record.message_post_with_source(
                'web_studio.notify_approval',
                author_id=entry.user_id.partner_id.id,
                partner_ids=partner_ids.ids,
                render_values={
                    'partner_ids': partner_ids,
                    'target_name': target_name,
                    'user_name': entry.user_id.display_name,
                    'approved': entry.approved,
                    },
                subtype_xmlid='mail.mt_note',
            )

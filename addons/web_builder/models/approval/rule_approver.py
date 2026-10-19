# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models, fields, _


class StudioApprovalRuleApprover(models.Model):
    _name = 'studio.approval.rule.approver'
    _description = "Approval Rule Approvers Enriched"
    _order = "id desc"
    _log_access = True  # explicit: we need create_uid and create_date

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    rule_id = fields.Many2one("studio.approval.rule", required=True, index=True, ondelete="cascade")
    date_to = fields.Date()
    is_delegation = fields.Boolean(default=True)

    @api.depends("create_uid", "user_id", "date_to")
    def _compute_display_name(self):
        for rec in self:
            name = []
            if rec.create_uid.name:
                name.extend([rec.create_uid.name, _("delegates to %s.", rec.user_id.name)])
            else:
                name.append(_("to %s.", rec.user_id.name))

            if rec.date_to:
                val = rec._fields["date_to"].convert_to_display_name(rec.date_to, rec)
                name.append(_("Until %s", val))
            rec.display_name = " ".join(name)

    def _is_valid(self):
        return not self.date_to or self.date_to >= fields.Date.context_today(self)

    def _filtered_valid(self):
        return self.filtered(lambda rec: rec._is_valid())

# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models, fields, _
from odoo.exceptions import AccessError
from odoo.fields import Command


class StudioApprovalRuleDelegate(models.TransientModel):
    _name = 'studio.approval.rule.delegate'
    _description = "Approval Rule Delegate"

    approval_rule_id = fields.Many2one("studio.approval.rule", required=True)
    approver_ids = fields.Many2many("res.users", string="Approvers",
        domain="['&', ('id', 'not in', [uid, 1]), ('share', '=', False)]")
    users_to_notify = fields.Many2many("res.users",
        relation="res_user_approval_rule_notify_rel",
        domain="[('id', 'not in', [1]), ('share', '=', False)]",
        string="Notify to")
    date_to = fields.Date(string="Until")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rule_su = rec.approval_rule_id.sudo()
            if not self.env.su and not rule_su.can_validate:
                raise AccessError(_("You are not allowed to delegate this approval rule."))
            rule_su._delegate_to(rec.approver_ids, rec.date_to)
            rule_su.write({"users_to_notify": rec.users_to_notify})
        return records

    @api.model
    def default_get(self, fields):
        vals = super().default_get(fields)
        default_rule_id = self.env.context.get("default_approval_rule_id")
        if default_rule_id and "approver_ids" in fields and "users_to_notify" in fields:
            rule = self.env["studio.approval.rule"].browse(default_rule_id).sudo()
            vals["approver_ids"] = [Command.link(log.user_id.id) for log in rule.approver_log_ids if log.is_delegation and log.create_uid.id == self.env.uid]
            vals["users_to_notify"] = [Command.link(uid) for uid in rule.users_to_notify.ids]
        return vals

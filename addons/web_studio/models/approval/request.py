# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import models, fields


class StudioApprovalRequest(models.Model):
    _name = 'studio.approval.request'
    _description = 'Studio Approval Request'

    mail_activity_id = fields.Many2one('mail.activity', string='Linked Activity', ondelete='cascade',
                                        required=True, index=True, inverse="_inverse_mail_activity_id")
    rule_id = fields.Many2one('studio.approval.rule', string='Approval Rule', ondelete='cascade',
                              required=True, index=True)
    res_id = fields.Many2oneReference(string='Record ID', model_field='model', required=True)
    model = fields.Char(related='mail_activity_id.res_model')

    def _inverse_mail_activity_id(self):
        for rec in self:
            rec.mail_activity_id.studio_approval_request_id = rec.id

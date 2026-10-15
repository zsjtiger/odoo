from odoo import models, fields, api


class SnowWorkflowNotification(models.AbstractModel):
    _name = 'snow.workflow.notification'

    def send_message_to_approver(self, receiver_uid, apply_name, apply_type, login_url):
        # 审批流调用入口，逻辑在snow_common中实现
        params = "Notice of pending review"
        return self.notification_send(params)

    def send_message_to_submitter(self, receiver_uid, apply_name, apply_type, login_url,
                                  action_user, action):
        # 审批流调用入口，逻辑在snow_common中实现
        params = "Applicant notification"
        return self.notification_send(params)

    def send_message_to_cc(self, receiver_uid, apply_name, apply_type, login_url):
        # 审批流调用入口，逻辑在snow_common中实现
        params = "Notice of carbon copy"
        return self.notification_send(params)

    def notification_send(self, params):
        print('Send notifications at the platform level: {}'.format(params))


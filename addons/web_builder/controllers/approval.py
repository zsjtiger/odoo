# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging


from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class StudioApprovalMixin:
    """ Studio approval rules configuration. """

    @http.route('/web_builder/edit_approval', type='jsonrpc', auth='user')
    def edit_approval(self, model, method, action, operations=None):
        for operation in operations:
            rule_id = operation[1]
            rule = request.env['studio.approval.rule'].browse(rule_id)
            if operation[0] == 'operation_approval_message':
                rule.message = operation[2]
            elif operation[0] == 'operation_different_users':
                rule.exclusive_user = operation[2]
        return True

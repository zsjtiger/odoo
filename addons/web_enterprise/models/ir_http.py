# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging
import re

from odoo import models
from odoo.http import request
from odoo.tools import html_sanitize

_logger = logging.getLogger(__name__)


MOBILE_APP_USER_AGENT = re.compile(r'OdooMobile \(iOS\)|OdooMobile.+Android', re.IGNORECASE)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def is_odoo_mobile_app(self):
        """Whether the request comes from the Odoo Mobile app (same check as isIosApp/isAndroidApp)."""
        return bool(MOBILE_APP_USER_AGENT.search(request.httprequest.user_agent.string or ''))

    @classmethod
    def _post_logout(cls):
        super()._post_logout()
        request.future_response.set_cookie('color_scheme', max_age=0)

    def color_scheme(self):
        user = request.env.user
        if user._is_public():
            return super().color_scheme()
        if (user_scheme := user.res_users_settings_id.color_scheme) in ('light', 'dark'):
            return user_scheme
        return request.httprequest.cookies.get('color_scheme') or super().color_scheme()

    def session_info(self):
        ICP = self.env['ir.config_parameter'].sudo()

        if self.env.user.has_group('base.group_system'):
            warn_enterprise = 'admin'
        elif self.env.user._is_internal():
            warn_enterprise = 'user'
        else:
            warn_enterprise = False

        result = super().session_info()
        result['support_url'] = "https://www.odoo.com/help"
        if warn_enterprise:
            result['warning'] = warn_enterprise
            result['expiration_date'] = ICP.get_str('database.expiration_date')
            result['expiration_reason'] = ICP.get_str('database.expiration_reason')
            if raw_message := ICP.get_str('sysadmin.message'):
                try:
                    sysadmin_message = json.loads(raw_message)
                    if 'message' in sysadmin_message:
                        sysadmin_message['message'] = html_sanitize(sysadmin_message['message'], sanitize_tags=False)
                    result['sysadmin_message'] = sysadmin_message
                except Exception:
                    _logger.exception('Failed to load sysadmin.message in ir.config_parameter')

        if self.env.user._is_internal():
            result['map_box_token'] = ICP.get_str('web_enterprise.token_map_box')

        return result

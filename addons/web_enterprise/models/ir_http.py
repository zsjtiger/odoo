# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import models
from odoo.http import request


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
        result = super().session_info()
        result['support_url'] = "https://www.odoo.com/help"
        if self.env.user.has_group('base.group_system'):
            result['warning'] = 'admin'
        elif self.env.user._is_internal():
            result['warning'] = 'user'
        return result

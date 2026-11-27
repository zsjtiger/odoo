# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class CompanyBranding(http.Controller):

    @http.route('/company_branding/config', type='http', auth='public', methods=['GET'], readonly=True)
    def company_branding_config(self, **kw):
        return request.make_json_response(request.env['res.company']._get_branding())

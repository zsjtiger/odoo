# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import datetime
import logging
import json
from ast import literal_eval

import requests

from odoo import api, fields, release
from odoo.models import AbstractModel
from odoo.tools import config

_logger = logging.getLogger(__name__)


class Publisher_WarrantyContract(AbstractModel):
    _name = 'publisher_warranty.contract'
    _description = 'Publisher Warranty Contract'

    @api.model
    def _get_message(self):
        Users = self.env['res.users']
        IrParamSudo = self.env['ir.config_parameter'].sudo()

        dbuuid = IrParamSudo.get_str('database.uuid')
        db_create_date = IrParamSudo.get_str('database.create_date')
        limit_date = fields.Datetime.now() - datetime.timedelta(15)
        nbr_users = Users.search_count([('active', '=', True)])
        nbr_active_users = Users.search_count([("login_date", ">=", limit_date), ('active', '=', True)])
        nbr_share_users = 0
        nbr_active_share_users = 0
        if "share" in Users._fields:
            nbr_share_users = Users.search_count([("share", "=", True), ('active', '=', True)])
            nbr_active_share_users = Users.search_count([("share", "=", True), ("login_date", ">=", limit_date), ('active', '=', True)])
        nbr_light_users = Users.search_count([("role", "=", "light_user"), ("active", "=", True)])
        nbr_active_light_users = Users.search_count([
            ("role", "=", "light_user"), ("login_date", ">=", limit_date), ("active", "=", True),
        ])
        user = self.env.user
        domain = [('application', '=', True), ('state', 'in', ['installed', 'to upgrade', 'to remove'])]
        apps = self.env['ir.module.module'].sudo().search_read(domain, ['name'])

        enterprise_code = IrParamSudo.get_str('database.enterprise_code')

        web_base_url = IrParamSudo.get_str('web.base.url')
        msg = {
            "dbuuid": dbuuid,
            "nbr_users": nbr_users,
            "nbr_active_users": nbr_active_users,
            "nbr_share_users": nbr_share_users,
            "nbr_active_share_users": nbr_active_share_users,
            "nbr_light_users": nbr_light_users,
            "nbr_active_light_users": nbr_active_light_users,
            "dbname": self.env.cr.dbname,
            "db_create_date": db_create_date,
            "version": release.version,
            "language": user.lang,
            "web_base_url": web_base_url,
            "apps": [app['name'] for app in apps],
            "enterprise_code": enterprise_code,
        }
        if user.partner_id.company_id:
            company_id = user.partner_id.company_id
            msg.update(company_id.read(["name", "email", "phone"])[0])
        return msg

    @api.model
    def _get_sys_logs(self):
        """
        Utility method to send a publisher warranty get logs messages.
        """
        msg = self._get_message()
        arguments = {'arg0': json.dumps(msg), "action": "update"}

        url = config.get("publisher_warranty_url")

        r = requests.post(url, data=arguments, timeout=30)
        r.raise_for_status()
        return literal_eval(r.text)

    def update_notification(self, cron_mode=True):
        """
        Subscription information is no longer synchronized with Odoo's publisher
        warranty server: this does nothing and does not contact the server.

        @param cron_mode: unused, kept for the signature of the cron.
        @type cron_mode: boolean
        """
        return True

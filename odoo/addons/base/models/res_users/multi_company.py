"""The users of several companies (res.users, multi-company fields)."""

from __future__ import annotations

from odoo import api, models
from odoo.fields import Command


class UsersMultiCompany(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        group_multi_company_id = self.env['ir.model.data']._xmlid_to_res_id(
            'base.group_multi_company', raise_if_not_found=False)
        if group_multi_company_id:
            for user in users:
                company_count = len(user.sudo().company_ids)
                if company_count <= 1 and group_multi_company_id in user.group_ids.ids:
                    user.write({'group_ids': [Command.unlink(group_multi_company_id)]})
                elif company_count > 1 and group_multi_company_id not in user.group_ids.ids:
                    user.write({'group_ids': [Command.link(group_multi_company_id)]})
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'company_ids' not in vals:
            return res
        group_multi_company_id = self.env['ir.model.data']._xmlid_to_res_id(
            'base.group_multi_company', raise_if_not_found=False)
        if group_multi_company_id:
            for user in self:
                company_count = len(user.sudo().company_ids)
                if company_count <= 1 and group_multi_company_id in user.group_ids.ids:
                    user.write({'group_ids': [Command.unlink(group_multi_company_id)]})
                elif company_count > 1 and group_multi_company_id not in user.group_ids.ids:
                    user.write({'group_ids': [Command.link(group_multi_company_id)]})
        return res

    @api.model
    def new(self, values=None, origin=None, ref=None):
        if values is None:
            values = {}
        user = super().new(values=values, origin=origin, ref=ref)

        if origin:
            return user
        group_multi_company_id = self.env['ir.model.data']._xmlid_to_res_id(
            'base.group_multi_company', raise_if_not_found=False)
        if group_multi_company_id:
            company_count = len(user.sudo().company_ids)
            if company_count <= 1 and group_multi_company_id in user.group_ids.ids:
                user.update({'group_ids': [Command.unlink(group_multi_company_id)]})
            elif company_count > 1 and group_multi_company_id not in user.group_ids.ids:
                user.update({'group_ids': [Command.link(group_multi_company_id)]})
        return user

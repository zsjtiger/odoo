# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.http import request

SKIP_CAPTCHA_LOGIN = object()

# Keys of the navigation bar (systray) items a user can hide, see `hidden_systray_items`.
SYSTRAY_ITEM_KEYS = ('ai', 'messaging', 'activity', 'studio', 'company')


class ResUsers(models.Model):
    _inherit = "res.users"

    systray_show_ai = fields.Boolean(string=_("AI"), compute="_compute_systray_visibility")
    systray_show_messaging = fields.Boolean(string=_("Chat"), compute="_compute_systray_visibility")
    systray_show_activity = fields.Boolean(string=_("Activities"), compute="_compute_systray_visibility")
    systray_show_studio = fields.Boolean(string=_("Studio"), compute="_compute_systray_visibility")
    systray_show_company = fields.Boolean(string=_("Company"), compute="_compute_systray_visibility")

    @api.depends_context("uid")
    def _compute_systray_visibility(self):
        for user in self:
            hidden = user.sudo().res_users_settings_ids[:1].hidden_systray_items or []
            user.systray_show_ai = 'ai' not in hidden
            user.systray_show_messaging = 'messaging' not in hidden
            user.systray_show_activity = 'activity' not in hidden
            user.systray_show_studio = 'studio' not in hidden
            user.systray_show_company = 'company' not in hidden

    def write(self, vals):
        shown = {key: vals.pop(f'systray_show_{key}') for key in SYSTRAY_ITEM_KEYS if f'systray_show_{key}' in vals}
        if shown:
            for user in self:
                settings = self.env['res.users.settings'].sudo()._find_or_create_for_user(user)
                hidden = set(settings.hidden_systray_items or [])
                for key, show in shown.items():
                    if show:
                        hidden.discard(key)
                    else:
                        hidden.add(key)
                settings.hidden_systray_items = sorted(hidden)
            self.invalidate_recordset([f'systray_show_{key}' for key in shown])
        return super().write(vals)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # if we have a search with a limit, move current user as the first result
        domain = Domain(domain or Domain.TRUE)
        user_list = super().name_search(name, domain, operator, limit)
        uid = self.env.uid
        # index 0 is correct not Falsy in this case, use None to avoid ignoring it
        if (index := next((i for i, (user_id, _name) in enumerate(user_list) if user_id == uid), None)) is not None:
            # move found user first
            user_tuple = user_list.pop(index)
            user_list.insert(0, user_tuple)
        elif limit is not None and len(user_list) == limit:
            # user not found and limit reached, try to find the user again
            if user_tuple := super().name_search(name, domain & Domain('id', '=', uid), operator, limit=1):
                user_list = [user_tuple[0], *user_list[:-1]]
        return user_list

    def _on_webclient_bootstrap(self):
        self.ensure_one()

    def _should_captcha_login(self, credential):
        if request and request.env.context.get('skip_captcha_login') is SKIP_CAPTCHA_LOGIN:
            return False
        return credential['type'] == 'password'

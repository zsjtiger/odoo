# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The records of the users: their creation, writes, deletion, searches and company-related values."""

from __future__ import annotations

from odoo import _
from odoo.api import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import (
    reset_cached_properties,
)
from .helpers import NO_GROUP_CHANGE_LOG

from .users import ResUsers, _logger

def init(self):
    cr = self.env.cr

    # allow setting plaintext passwords via SQL and have them
    # automatically encrypted at startup: look for passwords which don't
    # match the "extended" MCF and pass those through passlib.
    # Alternative: iterate on *all* passwords and use CryptContext.identify
    cr.execute(r"""
        SELECT id, password FROM res_users
        WHERE password IS NOT NULL
          AND password !~ '^\$[^$]+\$[^$]+\$.'
        """)
    if self.env.cr.rowcount:
        ResUsers = self.sudo()
        for uid, pw in cr.fetchall():
            ResUsers.browse(uid).password = pw


def _has_field_access(self, field, operation):
    # For writing a field, the user has elevated privileges (sudo or manager
    # group) or the field is marked as user_writeable. The records which the
    # user can change are protected by record rules.
    return super(ResUsers, self)._has_field_access(field, operation) and (
        operation != 'write'
        or getattr(field, 'user_writeable', False)
        or self.env.su
        or self.env.user.has_group('base.group_erp_manager')
    )


def create(self, vals_list):
    users = super(ResUsers, self).create(vals_list)
    setting_vals = []
    for user in users:
        if not user.sudo().res_users_settings_ids and user._is_internal():
            setting_vals.append({'user_id': user.id})
        # if partner is global we keep it that way
        if user.partner_id.company_id:
            user.partner_id.company_id = user.company_id
        user.partner_id.active = user.active
        # Generate employee initals as avatar for internal users without image
        if not user.image_1920 and not user.share and user.name:
            user.image_1920 = user.partner_id._avatar_generate_svg()

    if setting_vals:
        self.env['res.users.settings'].sudo().create(setting_vals)
    return users


def write(self, vals):
    if vals.get('active') and SUPERUSER_ID in self._ids:
        raise UserError(_("You cannot activate the superuser."))
    if vals.get('active') == False and self.env.uid in self._ids:  # noqa: E712
        raise UserError(_("You cannot deactivate the user you're currently logged in as."))

    if vals.get('active'):
        # unarchive partners before unarchiving the users
        self.partner_id.action_unarchive()

    if 'company_id' in vals or 'company_ids' in vals:
        # Access cache depends on the company, clear it
        self.env.transaction.invalidate_access_cache()
        # reset before the call to super to ensure `_check_company` sees the right company
        self._reset_cached_properties()

    if 'group_ids' in vals:
        old_group_ids = {user.id: user.group_ids.ids for user in self.sudo()}

    res = super(ResUsers, self).write(vals)

    if 'group_ids' in vals and self.env.context.get('no_group_change_log') is not NO_GROUP_CHANGE_LOG:
        # After write to make sure permission check passes
        self._log_group_changes(vals, old_group_ids)

    if 'company_id' in vals:
        for user in self:
            # if partner is global we keep it that way
            if user.partner_id.company_id and user.partner_id.company_id.id != vals['company_id']:
                user.partner_id.write({'company_id': user.company_id.id})

    if 'company_id' in vals or 'company_ids' in vals:
        # reset after the call to super to ensure the wrong value wasn't cached because of automations or hooks
        self.env.transaction.invalidate_access_cache()
        self._reset_cached_properties()
    elif 'tz' in vals:
        # also reset for changes of the time zone
        self._reset_cached_properties()

    if 'group_ids' in vals and any(self._ids):
        # clear caches linked to the users
        self.env.invalidate_all()
        self.env.transaction.invalidate_ormcache()

    # per-method / per-model caches have been removed so the various
    # clear_cache/clear_caches methods pretty much just end up calling
    # Transaction.invalidate_ormcache
    invalidation_fields = self._get_invalidation_fields()
    if not invalidation_fields.isdisjoint(vals) and any(self._ids):
        self.env.transaction.invalidate_ormcache()

    return res


def _reset_cached_properties(self):
    # Reset lazy properties `company` & `companies` on all envs,
    # This is unlikely in a business code to change the company of a user and then do business stuff
    # but in case it happens this is handled.
    # e.g. `account_test_savepoint.py` `setup_company_data`, triggered by `test_account_invoice_report.py`
    for env in list(self.env.transaction.envs):
        if env.user in self:
            reset_cached_properties(env)


def _unlink_except_master_data(self):
    portal_user_template = self.env.ref('base.template_portal_user_id', False)
    public_user = self.env.ref('base.public_user', False)
    if SUPERUSER_ID in self.ids:
        raise UserError(_('You can not remove the admin user as it is used internally for resources created by Odoo (updates, module installation, ...)'))
    user_admin = self.env.ref('base.user_admin', raise_if_not_found=False)
    if user_admin and user_admin in self:
        raise UserError(_('You cannot delete the admin user because it is utilized in various places (such as security configurations,...). Instead, archive it.'))
    self.env.transaction.invalidate_ormcache()
    if portal_user_template and portal_user_template in self:
        raise UserError(_('Deleting the template users is not allowed. Deleting this profile will compromise critical functionalities.'))
    if public_user and public_user in self:
        raise UserError(_("Deleting the public user is not allowed. Deleting this profile will compromise critical functionalities."))


def name_search(self, name='', domain=None, operator='ilike', limit=100):
    domain = Domain(domain or Domain.TRUE)
    # first search only by login, then the normal search
    if (
        name and not operator in Domain.NEGATIVE_OPERATORS
        and (user := self.search_fetch(Domain('login', '=', name) & domain, ['display_name']))
    ):
        return [(user.id, user.display_name)]
    return super(ResUsers, self).name_search(name, domain, operator, limit)


def _search_display_name(self, operator, value):
    domain = super(ResUsers, self)._search_display_name(operator, value)
    if operator in ('in', 'ilike') and value:
        name_domain = [('login', 'in', [value] if isinstance(value, str) else value)]
        # avoid searching both by login and name because they reside in two different tables
        # doing so prevents from using indexes and introduces a performance issue
        if users := self.search(name_domain):
            domain = [('id', 'in', users.ids)]
    return domain


def copy_data(self, default=None):
    default = dict(default or {})
    vals_list = super(ResUsers, self).copy_data(default=default)
    for user, vals in zip(self, vals_list):
        if ('name' not in default) and ('partner_id' not in default):
            vals['name'] = _("%s (copy)", user.name)
        if 'login' not in default:
            vals['login'] = _("%s (copy)", user.login)
    return vals_list


def _get_company_ids(self):
    # use search() instead of `self.company_ids` to avoid extra query for `active_test`
    domain = [('active', '=', True), ('user_ids', 'in', self.id)]
    return (self.company_id | self.env['res.company'].search(domain))._ids


def action_get(self):
    return self.sudo().env.ref('base.action_res_users_my').read()[0]


def _get_invalidation_fields(self):
    return {
        'group_ids', 'active', 'lang', 'tz', 'company_id', 'company_ids',
        *self._get_session_token_fields()
    }


def get_company_currency_id(self):
    return self.env.company.currency_id.id


def _register_hook(self):
    if hasattr(self, 'check_credentials'):
        _logger.warning("The check_credentials method of res.users has been renamed _check_credentials. One of your installed modules defines one, but it will not be called anymore.")

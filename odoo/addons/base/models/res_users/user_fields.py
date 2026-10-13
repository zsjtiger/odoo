# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The fields of the users: their checks, their computed values and onchanges, and the companies, the signatures and the settings."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo
from markupsafe import Markup
from odoo import _, models, tools
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import (
    email_domain_extract,
    is_html_empty,
)

from .users import ResUsers

def _check_company_domain(self, companies):
    if not companies:
        return Domain.TRUE
    company_ids = companies if isinstance(companies, str) else models.to_record_ids(companies)
    return Domain('company_ids', 'in', company_ids)


def _valid_field_parameter(self, field, name):
    # see `_has_field_access``
    return name == 'user_writeable' or super(ResUsers, self)._valid_field_parameter(field, name)


def _set_encrypted_password(self, uid, pw):
    assert self._crypt_context().identify(pw) != 'plaintext'

    self.env.cr.execute(
        'UPDATE res_users SET password=%s WHERE id=%s',
        (pw, uid)
    )
    self.browse(uid).invalidate_recordset(['password'])


def _compute_email_domain_placeholder(self):
    domain = email_domain_extract(self.env.user.email)
    self.email_domain_placeholder = _('e.g. %(placeholder)s', placeholder=f'email@{domain}') if domain else _('Email')


def _compute_signature(self):
    for user in self.filtered(lambda user: user.name and is_html_empty(user.signature)):
        user.signature = Markup('<div>%s</div>') % user['name']


def _compute_share(self):
    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
    internal_users = self.filtered_domain([('all_group_ids', 'in', [user_group_id])])
    internal_users.share = False
    (self - internal_users).share = True


def _recompute_user_share(self):
    """ Recalculate ``res.users.share`` and ``res.partner.partner_share`` in bulk via SQL.

        Changes in group relations or group hierarchy invalidate the share status of users
        and their associated partners. Resolving this dependency through standard ORM
        recordsets requires loading every user of every modified group, which causes
        memory overhead and poor performance O(N).

        This method executes a direct bulk SQL update in set-based queries, followed
        by ORM cache invalidation to ensure consistency across the environment.
        """
    internal_group_ids = list(self.env['res.groups']._get_internal_group_ids())

    # Invalidating the ORM cache to force reloading of SQL data
    self.env['res.users'].invalidate_model(['share'])
    self.env['res.partner'].invalidate_model(['partner_share'])

    # Update res_users: share = False if the user belongs to at least one internal group
    self.env.cr.execute("""
            WITH _share AS (
                SELECT u.id, any_value(r.gid) is null as share
                FROM res_users u
                LEFT JOIN res_groups_users_rel r
                    ON r.uid = u.id AND r.gid = ANY(%s)
                GROUP BY u.id
            )
            UPDATE res_users u
            SET share = s.share
            FROM _share s
            WHERE s.id = u.id AND s.share IS DISTINCT FROM u.share
        """, [internal_group_ids])

    # Update res_partner: partner_share IS NOT TRUE if the partner is linked to at least one internal user.
    self.env.cr.execute("""
            WITH _share AS (
                SELECT p.id, any_value(u.id) IS NULL as partner_share
                    FROM res_partner p
                LEFT JOIN res_users u
                    ON u.partner_id = p.id
                    AND u.share IS NOT TRUE
                GROUP BY p.id
            )
            UPDATE res_partner p
            SET partner_share = s.partner_share
            FROM _share s
            WHERE s.id = p.id AND s.partner_share IS DISTINCT FROM p.partner_share
        """)


def _compute_companies_count(self):
    self.companies_count = self.env['res.company'].sudo().search_count([])


def _compute_tz_offset(self):
    for user in self:
        user.tz_offset = datetime.datetime.now(ZoneInfo(user.tz or 'UTC')).strftime('%z')


def _compute_accesses_count(self):
    for user in self:
        groups = user.all_group_ids
        user.accesses_count = len(groups.access_ids)
        user.groups_count = len(groups)


def _compute_res_users_settings_id(self):
    for user in self:
        user.res_users_settings_id = user.res_users_settings_ids and user.res_users_settings_ids[0]


def _search_res_users_settings_id(self, operator, operand):
    return Domain('res_users_settings_ids', operator, operand)


def on_change_login(self):
    if self.login and tools.single_email_re.match(self.login):
        self.email = self.login


def onchange_parent_id(self):
    return self.partner_id.onchange_parent_id()


def _check_user_company(self):
    for user in self.filtered(lambda u: u.active):
        if user.company_id not in user.company_ids:
            raise ValidationError(
                _('Company %(company_name)s is not in the allowed companies for user %(user_name)s (%(company_allowed)s).',
                  company_name=user.company_id.name,
                  user_name=user.name,
                  company_allowed=', '.join(user.mapped('company_ids.name')))
            )


def _check_action_id(self):
    action_open_website = self.env.ref('base.action_open_website', raise_if_not_found=False)
    if action_open_website and any(user.action_id.id == action_open_website.id for user in self):
        raise ValidationError(_('The "App Switcher" action cannot be selected as home action.'))
    # We use sudo() because  "Access rights" admins can't read action models
    for user in self.sudo():
        if user.action_id.type == "ir.actions.client":
            # Prevent using reload actions.
            action = self.env["ir.actions.client"].browse(user.action_id.id)  # magic
            if action.tag == "reload":
                raise ValidationError(_('The "%s" action cannot be selected as home action.', action.name))

        elif user.action_id.type == "ir.actions.act_window":
            # Restrict actions that include 'active_id' in their context.
            action = self.env["ir.actions.act_window"].browse(user.action_id.id)  # magic
            if not action.context:
                continue
            if "active_id" in action.context:
                raise ValidationError(
                    _('The action "%s" cannot be set as the home action because it requires a record to be selected beforehand.', action.name)
                )


def _check_disjoint_groups(self):
    """We check that no users are both portal and users (same with public).
           This could typically happen because of implied groups.
        """
    user_type_groups = self.env['res.groups']._get_user_type_groups()
    for user in self:
        disjoint_groups = user.all_group_ids & user_type_groups
        if len(disjoint_groups) > 1:
            raise ValidationError(_(
                "User %(user)s cannot be at the same time in exclusive groups %(groups)s.",
                user=repr(user.name),
                groups=", ".join(repr(g.display_name) for g in disjoint_groups),
            ))


def _check_at_least_one_administrator(self):
    if not self.env.registry._init_modules:
        return  # ignore the constraint when updating the module 'base'
    if not self.env.ref('base.group_system').user_ids:
        raise ValidationError(_("You must have at least an administrator user."))

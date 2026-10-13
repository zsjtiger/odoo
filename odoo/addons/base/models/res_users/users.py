"""The users (res.users): their accounts, their groups, their companies and their sessions."""

from __future__ import annotations

import collections
import contextlib
import datetime
import hmac
import ipaddress
import logging
import time
from hashlib import sha256
from zoneinfo import ZoneInfo
from markupsafe import Markup
from odoo import _, api, fields, models, tools
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.http import request
from odoo.http.session import DEFAULT_LANG
from odoo.tools import (
    SQL,
    email_domain_extract,
    frozendict,
    is_html_empty,
    reset_cached_properties,
)
from odoo.tools.date_utils import all_timezones
from odoo.tools.sql import escape_like_value

from .crypt import CryptContext, MIN_ROUNDS
from .helpers import NO_GROUP_CHANGE_LOG, check_identity

_logger = logging.getLogger('odoo.addons.base.models.res_users')


class ResUsers(models.Model):
    """ User class. A res.users record models an OpenERP user and is different
        from an employee.

        res.users class now inherits from res.partner. The partner model is
        used to store the data related to the partner: lang, name, address,
        avatar, ... The user model is now dedicated to technical data.
    """
    _name = 'res.users'
    _description = 'User'
    _explanation = "Represents a person who has access to the system. Users have login credentials, assigned groups for security permissions, and are linked to a partner record for contact information."
    _inherits = {'res.partner': 'partner_id'}
    _order = 'name, login'
    _allow_sudo_commands = False

    def _check_company_domain(self, companies):
        if not companies:
            return Domain.TRUE
        company_ids = companies if isinstance(companies, str) else models.to_record_ids(companies)
        return Domain('company_ids', 'in', company_ids)

    def _valid_field_parameter(self, field, name):
        # see `_has_field_access``
        return name == 'user_writeable' or super()._valid_field_parameter(field, name)

    def _default_groups(self):
        """Default groups for employees

        All the groups of the Default User Group
        """
        groups = self.env.ref('base.group_user')
        default_group = self.env.ref('base.default_user_group', raise_if_not_found=False)
        if default_group:
            groups += default_group.implied_ids
        return groups

    partner_id = fields.Many2one('res.partner', required=True, ondelete='restrict', bypass_search_access=True, index=True,
        string='Related Partner', help='Partner-related data of the user')
    login = fields.Char(required=True, help="Used to log into the system")
    password = fields.Char(
        compute='_compute_password', inverse='_set_password', copy=False,
        help="Keep empty if you don't want the user to be able to connect on the system.")
    new_password = fields.Char(string='Set Password',
        compute='_compute_password', inverse='_set_new_password',
        help="Specify a value only when creating a user or if you're "\
             "changing the user's password, otherwise leave empty. After "\
             "a change of password, the user has to login again.")
    api_key_ids = fields.One2many('res.users.apikeys', 'user_id', string="API Keys", user_writeable=True)
    signature = fields.Html(string="Email Signature", compute='_compute_signature', readonly=False, store=True, user_writeable=True)
    active = fields.Boolean(default=True)
    active_partner = fields.Boolean(related='partner_id.active', readonly=True, string="Partner is Active")
    action_id = fields.Many2one('ir.actions.actions', string='Home Action',
        help="If specified, this action will be opened at log on for this user, in addition to the standard menu.")
    log_ids = fields.One2many('res.users.log', 'create_uid', string='User log entries')
    device_ids = fields.One2many('res.device', 'user_id', string='User devices')
    session_ids = fields.One2many('res.session', 'user_id', string='User sessions')
    login_date = fields.Datetime(related='log_ids.create_date', string='Latest Login', readonly=False)
    share = fields.Boolean(compute='_compute_share', compute_sudo=True, string='Share User', store=True,
         help="External user with limited access, created only for the purpose of sharing data.")
    companies_count = fields.Integer(compute='_compute_companies_count', string="Number of Companies")
    tz_offset = fields.Char(compute='_compute_tz_offset', string='Timezone offset')
    res_users_settings_ids = fields.One2many('res.users.settings', 'user_id')
    # Provide a target for relateds that is not a x2Many field.
    res_users_settings_id = fields.Many2one('res.users.settings', string="Settings", compute='_compute_res_users_settings_id', search='_search_res_users_settings_id')

    # Special behavior for this field: res.company.search() will only return the companies
    # available to the current user (should be the user's companies?), when the user_preference
    # context is set.
    company_id = fields.Many2one('res.company', string='Company', required=True,
        user_writeable=True,
        default=lambda self: self.env.company.id,
        help='The default company for this user.', context={'user_preference': True})
    company_ids = fields.Many2many('res.company', 'res_company_users_rel', 'user_id', 'cid',
        string='Companies', default=lambda self: self.env.company.ids)

    # overridden inherited fields to bypass access rights, in case you have
    # access to the user but not its corresponding partner
    name = fields.Char(related='partner_id.name', inherited=True, readonly=False, copy=True, user_writeable=True)
    email = fields.Char(related='partner_id.email', inherited=True, readonly=False, user_writeable=True)
    email_domain_placeholder = fields.Char(compute="_compute_email_domain_placeholder")
    phone = fields.Char(related='partner_id.phone', inherited=True, readonly=False, user_writeable=True)
    image_1920 = fields.Binary(related='partner_id.image_1920', inherited=True, readonly=False, user_writeable=True)
    lang = fields.Selection(related='partner_id.lang', inherited=True, readonly=False, user_writeable=True)
    tz = fields.Selection(related='partner_id.tz', inherited=True, readonly=False, user_writeable=True)

    group_ids = fields.Many2many('res.groups', 'res_groups_users_rel', 'uid', 'gid', string='Groups', default=lambda s: s._default_groups(), help="Groups explicitly assigned to the user")
    all_group_ids = fields.Many2many('res.groups', string="Groups and implied groups",
        compute='_compute_all_group_ids', compute_sudo=True, search='_search_all_group_ids')

    accesses_count = fields.Integer('# Access Rights', help='Number of access rights that apply to the current user',
                                    compute='_compute_accesses_count', compute_sudo=True)
    groups_count = fields.Integer('# Groups', help='Number of groups that apply to the current user',
                                  compute='_compute_accesses_count', compute_sudo=True)

    def _default_view_group_hierarchy(self):
        return self.env['res.groups']._get_view_group_hierarchy()

    view_group_hierarchy = fields.Json(string='Technical field for user group setting', store=False, copy=False, default=_default_view_group_hierarchy)
    role = fields.Selection([('light_user', 'Light'), ('regular_user', 'User'), ('group_system', 'Administrator')],
        compute='_compute_role', search='_search_role', readonly=False, string="Role")

    _login_key = models.Constraint("UNIQUE (login)",
        'You can not have two users with the same login!')

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

    def _set_password(self):
        ctx = self._crypt_context()
        for user in self:
            self._set_encrypted_password(user.id, ctx.hash(user.password))

    def _set_encrypted_password(self, uid, pw):
        assert self._crypt_context().identify(pw) != 'plaintext'

        self.env.cr.execute(
            'UPDATE res_users SET password=%s WHERE id=%s',
            (pw, uid)
        )
        self.browse(uid).invalidate_recordset(['password'])

    def _rpc_api_keys_only(self):
        """ To be overridden if RPC access needs to be restricted to API keys, e.g. for 2FA """
        return False

    def _get_auth_methods(self):
        """ Return a list of authentication methods available to the user. """
        self.ensure_one()
        auth_methods = []
        if mfa_type := self._mfa_type():
            auth_methods.append(mfa_type)
        auth_methods.append('password')
        return auth_methods

    def _check_credentials(self, credential, env):
        """ Validates the current user's password.

        Override this method to plug additional authentication methods.

        Overrides should:

        * call ``super`` to delegate to parents for credentials-checking
        * catch :class:`~odoo.exceptions.AccessDenied` and perform their
          own checking
        * (re)raise :class:`~odoo.exceptions.AccessDenied` if the
          credentials are still invalid according to their own
          validation method
        * return the ``auth_info``

        When trying to check for credentials validity, call
        :meth:`_check_credentials` instead.

        Credentials are considered to be untrusted user input, for more
        information please check :meth:`authenticate`

        :returns: ``auth_info`` dictionary containing:

          - uid: the uid of the authenticated user
          - auth_method: which method was used during authentication
          - mfa: whether mfa should be skipped or not, possible values:

            - enforce: enforce mfa no matter what (not yet implemented)
            - default: delegate to auth_totp
            - skip: skip mfa no matter what

          Examples:

          - ``{ 'uid': 20, 'auth_method': 'password',      'mfa': 'default' }``
          - ``{ 'uid': 17, 'auth_method': 'impersonation', 'mfa': 'enforce' }``
          - ``{ 'uid': 32, 'auth_method': 'webauthn',      'mfa': 'skip'    }``
        :rtype: dict
        """
        if not (credential['type'] == 'password' and credential.get('password')):
            raise AccessDenied()

        env = env or {}
        interactive = env.get('interactive', True)

        if interactive or not self.env.user._rpc_api_keys_only():
            if 'interactive' not in env:
                _logger.warning(
                    "_check_credentials without 'interactive' env key, assuming interactive login. \
                    Check calls and overrides to ensure the 'interactive' key is properly set in \
                    all _check_credentials environments"
                )

            self.env.cr.execute(
                "SELECT COALESCE(password, '') FROM res_users WHERE id=%s",
                [self.env.user.id]
            )
            [hashed] = self.env.cr.fetchone()
            valid, replacement = self._crypt_context()\
                .verify_and_update(credential['password'], hashed)
            if replacement is not None:
                self._set_encrypted_password(self.env.user.id, replacement)
                if request and self == self.env.user:
                    self.env.flush_all()
                    self.env.transaction.invalidate_ormcache()
                    # update session token so the user does not get logged out
                    new_token = self.env.user._compute_session_token(request.session.sid)
                    request.session.session_token = new_token

            if valid:
                return {
                    'uid': self.env.user.id,
                    'auth_method': 'password',
                    'mfa': 'default',
                }

        if not interactive:
            # 'rpc' scope does not really exist, we basically require a global key (scope NULL)
            if self.env['res.users.apikeys']._check_credentials(scope='rpc', key=credential['password']) == self.env.uid:
                return {
                    'uid': self.env.user.id,
                    'auth_method': 'apikey',
                    'mfa': 'default',
                }

            if self.env.user._rpc_api_keys_only():
                _logger.info(
                    "Invalid API key or password-based authentication attempted for a non-interactive (API) "
                    "context that requires API key authentication only."
                )

        raise AccessDenied()

    @api.depends_context('uid')
    def _compute_email_domain_placeholder(self):
        domain = email_domain_extract(self.env.user.email)
        self.email_domain_placeholder = _('e.g. %(placeholder)s', placeholder=f'email@{domain}') if domain else _('Email')

    def _compute_password(self):
        for user in self:
            user.password = ''
            user.new_password = ''

    def _set_new_password(self):
        for user in self:
            if not user.new_password:
                # Do not update the password if no value is provided, ignore silently.
                # For example web client submits False values for all empty fields.
                continue
            if user == self.env.user:
                # To change their own password, users must use the client-specific change password wizard,
                # so that the new password is immediately used for further RPC requests, otherwise the user
                # will face unexpected 'Access Denied' exceptions.
                raise UserError(_('Please use the change password wizard (in User Preferences or User menu) to change your own password.'))
            else:
                user.password = user.new_password

    @api.depends('all_group_ids')
    def _compute_role(self):
        group_system = self.env.ref('base.group_system', raise_if_not_found=False)
        group_user = self.env.ref('base.group_user', raise_if_not_found=False)

        for user in self:
            # A group is almost never held directly: ``base.group_user`` and the
            # light/regular tier both come from the application groups the user
            # is given, so the role is determined on the implied groups.
            all_groups = user.group_ids._origin.all_implied_ids
            user.role = (
                'group_system' if group_system and group_system in all_groups else
                'light_user' if group_user and group_user in all_groups and all_groups._is_light_groups() else
                'regular_user' if group_user and group_user in all_groups else
                False
            )

    @api.onchange('role')
    def _onchange_role(self):
        group_admin = self.env['res.groups'].new(origin=self.env.ref('base.group_system'))
        group_regular = self.env['res.groups'].new(origin=self.env.ref('base.group_user_regular'))
        group_user = self.env['res.groups'].new(origin=self.env.ref('base.group_user'))

        if self.role == 'regular_user':
            if group_regular not in self.all_group_ids:
                self.group_ids += group_regular
            self.group_ids -= group_admin
        elif self.role == 'group_system':
            self.group_ids += group_admin + group_user
        elif self.role == 'light_user':
            # If set to light user from portal or public user then add default groups
            if group_user not in self.all_group_ids:
                self.group_ids += self._default_groups()
            # Reduce all access to light user.
            self.group_ids = group_user + self.group_ids._origin._reduce_to_light_groups()

    def _search_role(self, operator, value):
        if operator != 'in':
            return NotImplemented

        group_definitions = self.env['res.groups']._get_group_definitions()
        light_group_ids = {group_definitions.get_id(xid) for xid in self.env['res.groups']._get_light_group_xmlids()}
        regular_group_ids = set(group_definitions.get_all_ids()) - light_group_ids

        is_system = Domain('all_group_ids', 'in', [self.env.ref('base.group_system').id])
        is_user_regular = Domain('all_group_ids', 'in', regular_group_ids)
        is_user = Domain('all_group_ids', 'in', [self.env.ref('base.group_user').id])
        domains_by_role = {
            'light_user': is_user & ~is_user_regular,
            'regular_user': is_user & is_user_regular & ~is_system,
            'group_system': is_system,
            False: ~is_user,
        }
        return Domain.OR([domains_by_role[v] for v in value if v in domains_by_role])

    @api.depends('group_ids.all_implied_ids')
    def _compute_all_group_ids(self):
        for user in self:
            user.all_group_ids = user.group_ids.all_implied_ids

    def _search_all_group_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        domain = Domain('group_ids.all_implied_ids', operator, value)
        if operator == 'in' and False in value:  # relation may be falsy
            domain |= Domain('group_ids', '=', False)
        return domain

    @api.depends('name')
    def _compute_signature(self):
        for user in self.filtered(lambda user: user.name and is_html_empty(user.signature)):
            user.signature = Markup('<div>%s</div>') % user['name']

    # To avoid a cache memory error, we do not use @api.depends('all_group_ids').
    # This update is made manually during group implying updates.
    @api.depends('group_ids')
    def _compute_share(self):
        user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
        internal_users = self.filtered_domain([('all_group_ids', 'in', [user_group_id])])
        internal_users.share = False
        (self - internal_users).share = True

    @api.model
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

    @api.depends('company_id')
    def _compute_companies_count(self):
        self.companies_count = self.env['res.company'].sudo().search_count([])

    @api.depends('tz')
    def _compute_tz_offset(self):
        for user in self:
            user.tz_offset = datetime.datetime.now(ZoneInfo(user.tz or 'UTC')).strftime('%z')

    @api.depends('all_group_ids')
    def _compute_accesses_count(self):
        for user in self:
            groups = user.all_group_ids
            user.accesses_count = len(groups.access_ids)
            user.groups_count = len(groups)

    @api.depends('res_users_settings_ids')
    def _compute_res_users_settings_id(self):
        for user in self:
            user.res_users_settings_id = user.res_users_settings_ids and user.res_users_settings_ids[0]

    @api.model
    def _search_res_users_settings_id(self, operator, operand):
        return Domain('res_users_settings_ids', operator, operand)

    @api.onchange('login')
    def on_change_login(self):
        if self.login and tools.single_email_re.match(self.login):
            self.email = self.login

    @api.onchange('parent_id')
    def onchange_parent_id(self):
        return self.partner_id.onchange_parent_id()

    @api.constrains('company_id', 'company_ids', 'active')
    def _check_user_company(self):
        for user in self.filtered(lambda u: u.active):
            if user.company_id not in user.company_ids:
                raise ValidationError(
                    _('Company %(company_name)s is not in the allowed companies for user %(user_name)s (%(company_allowed)s).',
                      company_name=user.company_id.name,
                      user_name=user.name,
                      company_allowed=', '.join(user.mapped('company_ids.name')))
                )

    @api.constrains('action_id')
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

    @api.constrains('group_ids')
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

    @api.constrains('group_ids')
    def _check_at_least_one_administrator(self):
        if not self.env.registry._init_modules:
            return  # ignore the constraint when updating the module 'base'
        if not self.env.ref('base.group_system').user_ids:
            raise ValidationError(_("You must have at least an administrator user."))

    @api.model
    def _has_field_access(self, field, operation):
        # For writing a field, the user has elevated privileges (sudo or manager
        # group) or the field is marked as user_writeable. The records which the
        # user can change are protected by record rules.
        return super()._has_field_access(field, operation) and (
            operation != 'write'
            or getattr(field, 'user_writeable', False)
            or self.env.su
            or self.env.user.has_group('base.group_erp_manager')
        )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
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

        res = super().write(vals)

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

    @api.ondelete(at_uninstall=True)
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

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        domain = Domain(domain or Domain.TRUE)
        # first search only by login, then the normal search
        if (
            name and not operator in Domain.NEGATIVE_OPERATORS
            and (user := self.search_fetch(Domain('login', '=', name) & domain, ['display_name']))
        ):
            return [(user.id, user.display_name)]
        return super().name_search(name, domain, operator, limit)

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if operator in ('in', 'ilike') and value:
            name_domain = [('login', 'in', [value] if isinstance(value, str) else value)]
            # avoid searching both by login and name because they reside in two different tables
            # doing so prevents from using indexes and introduces a performance issue
            if users := self.search(name_domain):
                domain = [('id', 'in', users.ids)]
        return domain

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for user, vals in zip(self, vals_list):
            if ('name' not in default) and ('partner_id' not in default):
                vals['name'] = _("%s (copy)", user.name)
            if 'login' not in default:
                vals['login'] = _("%s (copy)", user.login)
        return vals_list

    @api.model
    @api.ormcache('self.env.uid')
    def context_get(self):
        # use read() to not read other fields: this must work while modifying
        # the schema of models res.users or res.partner
        try:
            context = self.env.user.read(['lang', 'tz'], load=False)[0]
        except IndexError:
            # user not found, no context information
            return frozendict()
        context.pop('id')

        # ensure lang is set and available
        # context > request > company > english > any lang installed
        langs = [code for code, _ in self.env['res.lang'].get_installed()]
        lang = context.get('lang')
        if lang not in langs:
            lang = request.best_lang if request else None
            if lang not in langs:
                lang = self.env.user.with_context(prefetch_fields=False).company_id.partner_id.lang
                if lang not in langs:
                    lang = DEFAULT_LANG
                    if lang not in langs:
                        lang = langs[0] if langs else DEFAULT_LANG
        context['lang'] = lang

        # ensure uid is set
        context['uid'] = self.env.uid

        return frozendict(context)

    @api.ormcache('self.id')
    def _get_company_ids(self):
        # use search() instead of `self.company_ids` to avoid extra query for `active_test`
        domain = [('active', '=', True), ('user_ids', 'in', self.id)]
        return (self.company_id | self.env['res.company'].search(domain))._ids

    @api.model
    def action_get(self):
        return self.sudo().env.ref('base.action_res_users_my').read()[0]

    @api.model
    def _get_invalidation_fields(self):
        return {
            'group_ids', 'active', 'lang', 'tz', 'company_id', 'company_ids',
            *self._get_session_token_fields()
        }

    @api.model
    def _update_last_login(self):
        # only create new records to avoid any side-effect on concurrent transactions
        # extra records will be deleted by the periodical garbage collection
        self.env['res.users.log'].sudo().create({}) # populated by defaults

    @api.model
    def _get_login_domain(self, login):
        return Domain('login', '=', login)

    @api.model
    def _get_email_domain(self, email):
        return Domain('email', '=ilike', escape_like_value(email or ''))

    @api.model
    def _get_login_order(self):
        return self._order

    def _login(self, credential, user_agent_env):
        login = credential['login']
        ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'
        try:
            with self._assert_can_auth(user=login):
                user = self.sudo().search(self._get_login_domain(login), order=self._get_login_order(), limit=1)
                if not user:
                    # ruff: noqa: TRY301
                    raise AccessDenied()
                user = user.with_user(user).sudo()
                auth_info = user._check_credentials(credential, user_agent_env)
                tz = None
                if request and (browser_tz := request.cookies.get('tz')):
                    # browsers report the CLDR name, a deprecated alias for some
                    # zones, which ZoneInfo resolves to the canonical one
                    with contextlib.suppress(KeyError, ValueError):
                        tz = ZoneInfo(browser_tz).key
                if tz in all_timezones and (not user.tz or not user.login_date):
                    # first login or missing tz -> set tz to browser tz
                    user.tz = tz
                user._update_last_login()
        except AccessDenied:
            _logger.info("Login failed for login:%s from %s", login, ip)
            raise

        _logger.info("Login successful for login:%s from %s", login, ip)

        return auth_info

    def _log_group_changes(self, vals, old_group_ids, editing_groups=None):
        ip_addr = request.httprequest.remote_addr if request else 'n/a'
        for user in self:
            if editing_groups:
                _logger.info(
                    "Group change: user %d with IP %s changed groups of user %d who belonged to %s by editing res.groups %s with %s",
                    self.env.user.id, ip_addr, user.id, old_group_ids[user.id], editing_groups, vals['user_ids'],
                )
            else:
                _logger.info(
                    "Group change: user %d with IP %s changed groups of user %d who belonged to %s with changes %s",
                    self.env.user.id, ip_addr, user.id, old_group_ids[user.id], vals['group_ids'],
                )

    def authenticate(self, credential, user_agent_env):
        """Verifies and returns the user ID corresponding to the given
        ``credential``, or False if there was no matching user.

        :param dict credential: a dictionary where the `type` key defines the authentication method and
            additional keys are passed as required per authentication method.
            For example:
            - { 'type': 'password', 'login': 'username', 'password': '123456' }
            - { 'type': 'webauthn', 'webauthn_response': '{json data}' }
        :param dict user_agent_env: environment dictionary describing any
            relevant environment attributes
        :return: auth_info
        :rtype: dict
        """
        auth_info = self._login(credential, user_agent_env=user_agent_env)
        if user_agent_env and user_agent_env.get('base_location'):
            env = self.env(user=auth_info['uid'])
            if env.user.has_group('base.group_system'):
                # Successfully logged in as system user!
                # Attempt to guess the web base url...
                try:
                    base = user_agent_env['base_location']
                    ICP = env['ir.config_parameter']
                    if not ICP.get_bool('web.base.url.freeze'):
                        ICP.set_str('web.base.url', base)
                        _logger.info("web.base.url set to %s", base)
                except Exception:
                    _logger.exception("Failed to update web.base.url configuration parameter")
        return auth_info

    def _after_session_login(self):
        """Hook called after the user's HTTP session is fully authenticated."""

    @api.model
    @api.ormcache('uid', 'passwd')
    def _check_uid_passwd(self, uid, passwd):
        """Verifies that the given (uid, password) is authorized and
           raise an exception if it is not."""
        if not passwd:
            # empty passwords disallowed for obvious security reasons
            raise AccessDenied()

        with self._assert_can_auth(user=uid):
            user = self.with_user(uid).env.user
            if not user.active:
                raise AccessDenied()
            credential = {'login': user.login, 'password': passwd, 'type': 'password'}
            user._check_credentials(credential, {'interactive': False})

    def _get_session_token_fields(self):
        return {'id', 'login', 'password', 'active'}

    def _get_session_token_query_params(self):
        database_secret = SQL("SELECT value FROM ir_config_parameter WHERE key='database.secret'")
        fields = SQL(", ").join(
            SQL.identifier(self._table, fname)
            for fname in sorted(self._get_session_token_fields())
            # To handle `auth_passkey_key_ids`,
            # which we want in the `_get_session_token_fields` list for the cache invalidation mechanism
            # but which we do not want here as it isn't an actual column in the res_users table.
            # Instead, the left join to that table is done with an override of `_get_session_token_query_params`.
            if not self._fields[fname].relational
        )
        return {
            "select": SQL("(%s) as database_secret, %s", database_secret, fields),
            "from": SQL("res_users"),
            "joins": SQL(""),
            "where": SQL("res_users.id = %s", self.id),
            "group_by": SQL("res_users.id"),
        }

    @api.ormcache('sid')
    def _compute_session_token(self, sid):
        """ Compute a session token given a session id and a user id """
        # retrieve the fields used to generate the session token
        field_values = self._session_token_get_values()
        return self._session_token_hash_compute(sid, field_values)

    def _session_token_get_values(self):
        self.env.cr.execute(SQL(
            "SELECT %(select)s FROM %(from)s %(joins)s WHERE %(where)s GROUP BY %(group_by)s",
            **self._get_session_token_query_params(),
        ))
        if self.env.cr.rowcount != 1:
            self.env.transaction.invalidate_ormcache()
            return False
        data_fields = self.env.cr.fetchone()
        # create tuple with column name and value, allowing for overrides to manipulate the values
        cr_description = self.env.cr.description
        return tuple((column.name, data_fields[index]) for index, column in enumerate(cr_description))

    def _session_token_hash_compute(self, sid, field_values):
        if not field_values:
            return False
        # Generate hmac key using the column name and its value, only if the value is not None
        # To avoid invalidating sessions when installing a new feature modifying the session token computation
        # while not still being used.
        key_tuple = tuple((k, v) for k, v in field_values if v is not None)
        # encode the key tuple to a bytestring
        key = str(key_tuple).encode()
        # hmac the session id
        data = sid.encode()
        h = hmac.new(key, data, sha256)
        # return the session token with a prefix version
        return h.hexdigest()

    def _legacy_session_token_hash_compute(self, sid):
        field_values = self._session_token_get_values()
        if not field_values:
            return False
        # generate hmac key
        key = ('%s' % (tuple(f[1] for f in field_values),)).encode()
        # hmac the session id
        data = sid.encode()
        h = hmac.new(key, data, sha256)
        # keep in the cache the token
        return h.hexdigest()

    @api.model
    def change_password(self, old_passwd, new_passwd):
        """Change current user password. Old password must be provided explicitly
        to prevent hijacking an existing user session, or for cases where the cleartext
        password is not used to authenticate requests.

        :return: True
        :raise: odoo.exceptions.AccessDenied when old password is wrong
        :raise: odoo.exceptions.UserError when new password is not set or empty
        """
        if not old_passwd:
            raise AccessDenied()

        # alternatively: use identitycheck wizard?
        credential = {'login': self.env.user.login, 'password': old_passwd, 'type': 'password'}
        self._check_credentials(credential, {'interactive': True})

        # use self.env.user here, because it has uid=SUPERUSER_ID
        self.env.user._change_password(new_passwd)
        return True

    def _change_password(self, new_passwd):
        new_passwd = new_passwd.strip()
        if not new_passwd:
            raise UserError(_("Setting empty passwords is not allowed for security reasons!"))

        self._log_change_password("Password")

        self.password = new_passwd

    def _log_change_password(self, description):
        ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'
        _logger.info(
            "%s change for %r (#%d) by %r (#%d) from %s",
            description,
            self.login,
            self.id,
            self.env.user.login,
            self.env.user.id,
            ip,
        )

    def _deactivate_portal_user(self, **post):
        """Try to remove the current portal user.

        This is used to give the opportunity to portal users to de-activate their accounts.
        Indeed, as the portal users can easily create accounts, they will sometimes wish
        it removed because they don't use this Odoo portal anymore.

        Before this feature, they would have to contact the website or the support to get
        their account removed, which could be tedious.
        """
        non_portal_users = self.filtered(lambda user: not user.share)
        if non_portal_users:
            raise AccessDenied(_(
                'Only the portal users can delete their accounts. '
                'The user(s) %s can not be deleted.',
                ', '.join(non_portal_users.mapped('name')),
            ))

        ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'

        res_users_deletion_values = []

        for user in self:
            _logger.info(
                'Account deletion asked for "%s" (#%i) from %s. '
                'Archive the user and remove login information.',
                user.login, user.id, ip,
            )

            user.write({
                'login': f'__deleted_user_{user.id}_{time.time()}',
                'password': '',
            })
            user.api_key_ids._remove()

            res_users_deletion_values.append({
                'user_id': user.id,
                'state': 'todo',
            })

        # Here we try to archive the user / partner, and then add the user in a deletion
        # queue, to remove it from the database. As the deletion might fail (if the
        # partner is related to an invoice e.g.) it's important to archive it here.
        try:
            # A user can not self-deactivate
            self.with_user(SUPERUSER_ID).action_archive()
        except Exception:
            pass
        try:
            self.partner_id.action_archive()
        except Exception:
            pass
        # Add users in the deletion queue
        self.env['res.users.deletion'].create(res_users_deletion_values)

    def preference_save(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'reload_context',
        }

    @check_identity
    def action_change_password_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_model': 'change.password.wizard',
            'view_mode': 'form',
            'name': 'Change Password',
            'context': {'active_ids': self.ids, 'active_model': 'res.users'}
        }

    @check_identity
    def preference_change_password(self):
        return {
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_model': 'change.password.own',
            'view_mode': 'form',
        }

    @check_identity
    def api_key_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users.apikeys.description',
            'name': 'Create API Key',
            'target': 'new',
            'views': [(False, 'form')],
        }

    @check_identity
    def action_revoke_all_devices(self):
        # self.env.user is sudo by default
        # Need sudo to bypass access error for removing the devices of portal user
        return (self.env.user if self.id == self.env.uid else self)._action_revoke_all_devices()

    def _action_revoke_all_devices(self):
        sessions = self.env["res.session"].search([("user_id", "=", self.id)])
        sessions.filtered(lambda d: not d.is_current)._revoke()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.readonly
    def has_groups(self, group_spec: str) -> bool:
        """ Return whether user ``self`` satisfies the given group restrictions
        ``group_spec``, i.e., whether it is member of at least one of the groups,
        and is not a member of any of the groups preceded by ``!``.

        Note that the group ``"base.group_no_one"`` is only effective in debug
        mode, just like method :meth:`~.has_group` does.

        :param str group_spec: comma-separated list of fully-qualified group
            external IDs, optionally preceded by ``!``.
            Example:``"base.group_user,base.group_portal,!base.group_system"``.
        """
        if group_spec == '.':
            return False

        positives = []
        negatives = []
        for group_ext_id in group_spec.split(','):
            group_ext_id = group_ext_id.strip()
            if group_ext_id.startswith('!'):
                negatives.append(group_ext_id[1:])
            else:
                positives.append(group_ext_id)

        # for the sake of performance, check negatives first
        if any(self.has_group(ext_id) for ext_id in negatives):
            return False
        if any(self.has_group(ext_id) for ext_id in positives):
            return True
        return not positives

    @api.readonly
    def has_group(self, group_ext_id: str) -> bool:
        """ Return whether user ``self`` belongs to the given group (given by its
        fully-qualified external ID).

        Note that the group ``"base.group_no_one"`` is only effective in debug
        mode: the method returns ``True`` if the user belongs to the group and
        the current request is in debug mode.
        """
        self.ensure_one()
        if not (self.env.su or self == self.env.user or self.env.user._has_group('base.group_user')):
            # this prevents RPC calls from non-internal users to retrieve
            # information about other users
            raise AccessError(_("You can ony call user.has_group() with your current user."))

        result = self._has_group(group_ext_id)
        if group_ext_id == 'base.group_no_one':
            result = result and bool(request and request.session.debug)
        return result

    def _has_group(self, group_ext_id: str) -> bool:
        """ Return whether user ``self`` belongs to the given group.

        :param str group_ext_id: external ID (XML ID) of the group.
           Must be provided in fully-qualified form (``module.ext_id``), as there
           is no implicit module to use..
        :return: True if user ``self`` is a member of the group with the
           given external ID (XML ID), else False.
        """
        group_id = self.env['res.groups']._get_group_definitions().get_id(group_ext_id)
        # for new record don't fill the ormcache
        return group_id in (self._get_group_ids() if self.id else self.all_group_ids._origin._ids)

    @api.ormcache('self.id')
    def _get_group_ids(self):
        """ Return ``self``'s group ids (as a tuple)."""
        self.ensure_one()
        # `with_context({})` because this method is decorated with `@ormcache('self._ids')`,
        # it cannot depend on the context (e.g. `active_test`, `lang`, ...)
        return self.with_context({}).all_group_ids._ids

    def _action_show(self):
        """Directly access the form view"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users',
            'context': {'create': False},
            'name': _('Users'),
            'view_mode': 'form',
            'views': [[self.env.ref('base.view_users_form').id, 'form']],
            'domain': [('id', 'in', self.ids)],
        }

    def action_show_groups(self):
        self.ensure_one()
        return {
            'name': _('Groups'),
            'view_mode': 'list,form',
            'res_model': 'res.groups',
            'type': 'ir.actions.act_window',
            'context': {'create': False, 'delete': False},
            'domain': [('id', 'in', self.all_group_ids.ids)],
            'target': 'current',
        }

    def action_show_accesses(self):
        self.ensure_one()
        return {
            'name': _('Access Rights'),
            'view_mode': 'list,form',
            'res_model': 'ir.access',
            'type': 'ir.actions.act_window',
            'context': {'create': False, 'delete': False},
            'domain': [('group_id', 'in', self.all_group_ids.ids)],
            'target': 'current',
        }

    def _is_internal(self):
        self.ensure_one()
        return self.sudo().has_group('base.group_user')

    def _is_regular(self):
        """ An internal user that is not a light one. """
        self.ensure_one()
        return self.sudo().role in ('regular_user', 'group_system')

    def _is_portal(self):
        self.ensure_one()
        return self.sudo().has_group('base.group_portal')

    def _is_public(self):
        self.ensure_one()
        return self.sudo().has_group('base.group_public')

    def _is_system(self):
        self.ensure_one()
        return self.sudo().has_group('base.group_system')

    def _is_admin(self):
        self.ensure_one()
        return self._is_superuser() or self.sudo().has_group('base.group_erp_manager')

    def _is_superuser(self):
        self.ensure_one()
        return self.id == SUPERUSER_ID

    @api.model
    def get_company_currency_id(self):
        return self.env.company.currency_id.id

    @api.ormcache(cache='stable')
    def _crypt_context(self):
        """ Passlib CryptContext instance used to encrypt and verify
        passwords. Can be overridden if technical, legal or political matters
        require different kdfs than the provided default.

        The work factor of the default KDF can be configured using the
        ``password.hashing.rounds`` ICP.
        """
        cfg = self.env['ir.config_parameter'].sudo()
        return CryptContext(
            # kdf which can be verified by the context. The default encryption
            # kdf is the first of the list
            ['pbkdf2_sha512', 'plaintext'],
            # deprecated algorithms are still verified as usual, but
            # ``needs_update`` will indicate that the stored hash should be
            # replaced by a more recent algorithm.
            deprecated=['auto'],
            pbkdf2_sha512__rounds=max(MIN_ROUNDS, cfg.get_int('password.hashing.rounds')),
        )

    @contextlib.contextmanager
    def _assert_can_auth(self, user=None):
        """ Checks that the current environment even allows the current auth
        request to happen.

        The baseline implementation is a simple linear login cooldown: after
        a number of failures trying to log-in, the user (by login) is put on
        cooldown. During the cooldown period, login *attempts* are ignored
        and logged.

        :param user: user id or login, for logging purpose

        .. warning::

            The login counter is not shared between workers and not
            specifically thread-safe, the feature exists mostly for
            rate-limiting on large number of login attempts (brute-forcing
            passwords) so that should not be much of an issue.

            For a more complex strategy (e.g. database or distribute storage)
            override this method. To simply change the cooldown criteria
            (configuration, ...) override _on_login_cooldown instead.

        .. note::

            This is a *context manager* so it can be called around the login
            procedure without having to call it itself.
        """
        # needs request for remote address
        if not request:
            yield
            return

        reg = self.env.registry
        failures_map = getattr(reg, '_login_failures', None)
        if failures_map is None:
            failures_map = reg._login_failures = collections.defaultdict(lambda : (0, datetime.datetime.min))

        source = request.httprequest.remote_addr
        (failures, previous) = failures_map[source]
        if self._on_login_cooldown(failures, previous):
            _logger.warning(
                "Login attempt ignored for %s (user %r) on %s: "
                "%d failures since last success, last failure at %s. "
                "You can configure the number of login failures before a "
                "user is put on cooldown as well as the duration in the "
                "System Parameters. Disable this feature by setting "
                "\"base.login_cooldown_after\" to 0.",
                source, user or "?", self.env.cr.dbname, failures, previous)
            if ipaddress.ip_address(source).is_private:
                _logger.warning(
                    "The rate-limited IP address %s is classified as private "
                    "and *might* be a proxy. If your Odoo is behind a proxy, "
                    "it may be mis-configured. Check that you are running "
                    "Odoo in Proxy Mode and that the proxy is properly configured, see "
                    "https://www.odoo.com/documentation/latest/administration/install/deploy.html#https for details.",
                    source
                )
            raise AccessDenied(_("Too many login failures, please wait a bit before trying again."))

        try:
            yield
        except AccessDenied:
            (failures, __) = reg._login_failures[source]
            reg._login_failures[source] = (failures + 1, datetime.datetime.now())
            raise
        else:
            reg._login_failures.pop(source, None)

    def _on_login_cooldown(self, failures, previous):
        """ Decides whether the user trying to log in is currently
        "on cooldown" and not even allowed to attempt logging in.

        The default cooldown function simply puts the user on cooldown for
        <login_cooldown_duration> seconds after each failure following the
        <login_cooldown_after>th (0 to disable).

        Can be overridden to implement more complex backoff strategies, or
        e.g. wind down or reset the cooldown period as the previous failure
        recedes into the far past.

        :param int failures: number of recorded failures (since last success)
        :param previous: timestamp of previous failure
        :type previous:  datetime.datetime
        :returns: whether the user is currently in cooldown phase (true if cooldown, false if no cooldown and login can continue)
        :rtype: bool
        """
        cfg = self.env['ir.config_parameter'].sudo()
        min_failures = cfg.get_int('base.login_cooldown_after', 5)
        if min_failures == 0:
            return False

        delay = cfg.get_int('base.login_cooldown_duration') or 60
        return failures >= min_failures and (datetime.datetime.now() - previous) < datetime.timedelta(seconds=delay)

    def _register_hook(self):
        if hasattr(self, 'check_credentials'):
            _logger.warning("The check_credentials method of res.users has been renamed _check_credentials. One of your installed modules defines one, but it will not be called anymore.")

    def _mfa_type(self):
        """ If an MFA method is enabled, returns its type as a string. """
        return

    def _mfa_url(self):
        """ If an MFA method is enabled, returns the URL for its second step. """
        return


ResUsersPatchedInTest = ResUsers

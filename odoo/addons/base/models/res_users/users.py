# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The users (res.users): the model, its fields, the authentication that reads the request, and the login. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import collections
import contextlib
import datetime
import ipaddress
import logging
import time
from zoneinfo import ZoneInfo
from odoo import _, api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessDenied, AccessError
from odoo.http import request
from odoo.http.session import DEFAULT_LANG
from odoo.tools import (
    frozendict,
)
from odoo.tools.date_utils import all_timezones
from .helpers import check_identity


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
        return _user_fields._check_company_domain(self, companies)
    def _valid_field_parameter(self, field, name):
        return _user_fields._valid_field_parameter(self, field, name)
    def _default_groups(self):
        return _user_groups._default_groups(self)
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
    res_users_settings_id = fields.Many2one('res.users.settings', string="Settings", compute='_compute_res_users_settings_id', search='_search_res_users_settings_id')
    company_id = fields.Many2one('res.company', string='Company', required=True,
        user_writeable=True,
        default=lambda self: self.env.company.id,
        help='The default company for this user.', context={'user_preference': True})
    company_ids = fields.Many2many('res.company', 'res_company_users_rel', 'user_id', 'cid',
        string='Companies', default=lambda self: self.env.company.ids)
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
        return _user_groups._default_view_group_hierarchy(self)
    view_group_hierarchy = fields.Json(string='Technical field for user group setting', store=False, copy=False, default=_default_view_group_hierarchy)
    role = fields.Selection([('light_user', 'Light'), ('regular_user', 'User'), ('group_system', 'Administrator')],
        compute='_compute_role', search='_search_role', readonly=False, string="Role")
    _login_key = models.Constraint("UNIQUE (login)",
        'You can not have two users with the same login!')
    def init(self):
        return _user_records.init(self)
    def _set_password(self):
        return _user_passwords._set_password(self)
    def _set_encrypted_password(self, uid, pw):
        return _user_fields._set_encrypted_password(self, uid, pw)
    def _rpc_api_keys_only(self):
        return _user_sessions._rpc_api_keys_only(self)
    def _get_auth_methods(self):
        return _user_sessions._get_auth_methods(self)
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
        return _user_fields._compute_email_domain_placeholder(self)
    def _compute_password(self):
        return _user_passwords._compute_password(self)
    def _set_new_password(self):
        return _user_passwords._set_new_password(self)
    @api.depends('all_group_ids')
    def _compute_role(self):
        return _user_groups._compute_role(self)
    @api.onchange('role')
    def _onchange_role(self):
        return _user_groups._onchange_role(self)
    def _search_role(self, operator, value):
        return _user_groups._search_role(self, operator, value)
    @api.depends('group_ids.all_implied_ids')
    def _compute_all_group_ids(self):
        return _user_groups._compute_all_group_ids(self)
    def _search_all_group_ids(self, operator, value):
        return _user_groups._search_all_group_ids(self, operator, value)
    @api.depends('name')
    def _compute_signature(self):
        return _user_fields._compute_signature(self)
    @api.depends('group_ids')
    def _compute_share(self):
        return _user_fields._compute_share(self)
    @api.model
    def _recompute_user_share(self):
        return _user_fields._recompute_user_share(self)
    @api.depends('company_id')
    def _compute_companies_count(self):
        return _user_fields._compute_companies_count(self)
    @api.depends('tz')
    def _compute_tz_offset(self):
        return _user_fields._compute_tz_offset(self)
    @api.depends('all_group_ids')
    def _compute_accesses_count(self):
        return _user_fields._compute_accesses_count(self)
    @api.depends('res_users_settings_ids')
    def _compute_res_users_settings_id(self):
        return _user_fields._compute_res_users_settings_id(self)
    @api.model
    def _search_res_users_settings_id(self, operator, operand):
        return _user_fields._search_res_users_settings_id(self, operator, operand)
    @api.onchange('login')
    def on_change_login(self):
        return _user_fields.on_change_login(self)
    @api.onchange('parent_id')
    def onchange_parent_id(self):
        return _user_fields.onchange_parent_id(self)
    @api.constrains('company_id', 'company_ids', 'active')
    def _check_user_company(self):
        return _user_fields._check_user_company(self)
    @api.constrains('action_id')
    def _check_action_id(self):
        return _user_fields._check_action_id(self)
    @api.constrains('group_ids')
    def _check_disjoint_groups(self):
        return _user_fields._check_disjoint_groups(self)
    @api.constrains('group_ids')
    def _check_at_least_one_administrator(self):
        return _user_fields._check_at_least_one_administrator(self)
    @api.model
    def _has_field_access(self, field, operation):
        return _user_records._has_field_access(self, field, operation)
    @api.model_create_multi
    def create(self, vals_list):
        return _user_records.create(self, vals_list)
    def write(self, vals):
        return _user_records.write(self, vals)
    def _reset_cached_properties(self):
        return _user_records._reset_cached_properties(self)
    @api.ondelete(at_uninstall=True)
    def _unlink_except_master_data(self):
        return _user_records._unlink_except_master_data(self)
    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        return _user_records.name_search(self, name, domain, operator, limit)
    @api.model
    def _search_display_name(self, operator, value):
        return _user_records._search_display_name(self, operator, value)
    def copy_data(self, default=None):
        return _user_records.copy_data(self, default)
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
        return _user_records._get_company_ids(self)
    @api.model
    def action_get(self):
        return _user_records.action_get(self)
    @api.model
    def _get_invalidation_fields(self):
        return _user_records._get_invalidation_fields(self)
    @api.model
    def _update_last_login(self):
        return _user_sessions._update_last_login(self)
    @api.model
    def _get_login_domain(self, login):
        return _user_sessions._get_login_domain(self, login)
    @api.model
    def _get_email_domain(self, email):
        return _user_sessions._get_email_domain(self, email)
    @api.model
    def _get_login_order(self):
        return _user_sessions._get_login_order(self)
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
        return _user_sessions.authenticate(self, credential, user_agent_env)
    def _after_session_login(self):
        return _user_sessions._after_session_login(self)
    @api.model
    @api.ormcache('uid', 'passwd')
    def _check_uid_passwd(self, uid, passwd):
        return _user_passwords._check_uid_passwd(self, uid, passwd)
    def _get_session_token_fields(self):
        return _user_sessions._get_session_token_fields(self)
    def _get_session_token_query_params(self):
        return _user_sessions._get_session_token_query_params(self)
    @api.ormcache('sid')
    def _compute_session_token(self, sid):
        return _user_sessions._compute_session_token(self, sid)
    def _session_token_get_values(self):
        return _user_sessions._session_token_get_values(self)
    def _session_token_hash_compute(self, sid, field_values):
        return _user_sessions._session_token_hash_compute(self, sid, field_values)
    def _legacy_session_token_hash_compute(self, sid):
        return _user_sessions._legacy_session_token_hash_compute(self, sid)
    @api.model
    def change_password(self, old_passwd, new_passwd):
        return _user_passwords.change_password(self, old_passwd, new_passwd)
    def _change_password(self, new_passwd):
        return _user_passwords._change_password(self, new_passwd)
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
        return _user_sessions.preference_save(self)
    @check_identity
    def action_change_password_wizard(self):
        return _user_passwords.action_change_password_wizard(self)
    @check_identity
    def preference_change_password(self):
        return _user_passwords.preference_change_password(self)
    @check_identity
    def api_key_wizard(self):
        return _user_sessions.api_key_wizard(self)
    @check_identity
    def action_revoke_all_devices(self):
        return _user_sessions.action_revoke_all_devices(self)
    def _action_revoke_all_devices(self):
        return _user_sessions._action_revoke_all_devices(self)
    @api.readonly
    def has_groups(self, group_spec: str) -> bool:
        return _user_groups.has_groups(self, group_spec)
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
        return _user_groups._has_group(self, group_ext_id)
    @api.ormcache('self.id')
    def _get_group_ids(self):
        return _user_groups._get_group_ids(self)
    def _action_show(self):
        return _user_groups._action_show(self)
    def action_show_groups(self):
        return _user_groups.action_show_groups(self)
    def action_show_accesses(self):
        return _user_groups.action_show_accesses(self)
    def _is_internal(self):
        return _user_sessions._is_internal(self)
    def _is_regular(self):
        return _user_sessions._is_regular(self)
    def _is_portal(self):
        return _user_sessions._is_portal(self)
    def _is_public(self):
        return _user_sessions._is_public(self)
    def _is_system(self):
        return _user_sessions._is_system(self)
    def _is_admin(self):
        return _user_sessions._is_admin(self)
    def _is_superuser(self):
        return _user_sessions._is_superuser(self)
    @api.model
    def get_company_currency_id(self):
        return _user_records.get_company_currency_id(self)
    @api.ormcache(cache='stable')
    def _crypt_context(self):
        return _user_passwords._crypt_context(self)
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
        return _user_sessions._on_login_cooldown(self, failures, previous)
    def _register_hook(self):
        return _user_records._register_hook(self)
    def _mfa_type(self):
        return _user_sessions._mfa_type(self)
    def _mfa_url(self):
        return _user_sessions._mfa_url(self)


_logger = logging.getLogger('odoo.addons.base.models.res_users')


ResUsersPatchedInTest = ResUsers


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import user_fields as _user_fields, user_groups as _user_groups, user_records as _user_records, user_passwords as _user_passwords, user_sessions as _user_sessions  # noqa: E402

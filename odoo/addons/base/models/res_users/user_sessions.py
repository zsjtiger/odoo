# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The sessions of the users: the authentication, the session tokens, the login cooldowns, the API keys and the user types."""

from __future__ import annotations

import datetime
import hmac
from hashlib import sha256
from odoo.api import SUPERUSER_ID
from odoo.fields import Domain
from odoo.tools import (
    SQL,
)
from odoo.tools.sql import escape_like_value

from .users import _logger

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


def _update_last_login(self):
    # only create new records to avoid any side-effect on concurrent transactions
    # extra records will be deleted by the periodical garbage collection
    self.env['res.users.log'].sudo().create({}) # populated by defaults


def _get_login_domain(self, login):
    return Domain('login', '=', login)


def _get_email_domain(self, email):
    return Domain('email', '=ilike', escape_like_value(email or ''))


def _get_login_order(self):
    return self._order


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


def preference_save(self):
    return {
        'type': 'ir.actions.client',
        'tag': 'reload_context',
    }


def api_key_wizard(self):
    return {
        'type': 'ir.actions.act_window',
        'res_model': 'res.users.apikeys.description',
        'name': 'Create API Key',
        'target': 'new',
        'views': [(False, 'form')],
    }


def action_revoke_all_devices(self):
    # self.env.user is sudo by default
    # Need sudo to bypass access error for removing the devices of portal user
    return (self.env.user if self.id == self.env.uid else self)._action_revoke_all_devices()


def _action_revoke_all_devices(self):
    sessions = self.env["res.session"].search([("user_id", "=", self.id)])
    sessions.filtered(lambda d: not d.is_current)._revoke()
    return {'type': 'ir.actions.client', 'tag': 'reload'}


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


def _mfa_type(self):
    """ If an MFA method is enabled, returns its type as a string. """
    return


def _mfa_url(self):
    """ If an MFA method is enabled, returns the URL for its second step. """
    return

"""The API keys of the users (res.users.apikeys), their descriptions and their checks."""

from __future__ import annotations

import binascii
import datetime
import logging
import os
from hashlib import sha256
from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import (
    SQL,
    str2bool,
)

from .crypt import CryptContext
from .helpers import check_identity

_logger = logging.getLogger('odoo.addons.base.models.res_users')


API_KEY_SIZE = 20 # in bytes


INDEX_SIZE = 8 # in hex digits, so 4 bytes, or 20% of the key


KEY_CRYPT_CONTEXT = CryptContext(
    # default is 29000 rounds which is 25~50ms, which is probably unnecessary
    # given in this case all the keys are completely random data: dictionary
    # attacks on API keys isn't much of a concern
    ['pbkdf2_sha512'], pbkdf2_sha512__rounds=6000,
)


DEFAULT_PROGRAMMATIC_API_KEYS_LIMIT = 10  # programmatic API key creation is refused if the user already has at least this amount of API keys


class ResUsersApikeys(models.Model):
    _name = 'res.users.apikeys'
    _description = 'User API Key'
    _auto = False # so we can have a secret column
    _allow_sudo_commands = False

    name = fields.Char("Description", required=True, readonly=True)
    user_id = fields.Many2one('res.users', index=True, required=True, readonly=True, ondelete="cascade")
    scope = fields.Char("Scope", required=True, readonly=True)
    create_date = fields.Datetime("Creation Date", readonly=True)
    expiration_date = fields.Datetime("Expiration Date", readonly=True)

    def init(self):
        table = SQL.identifier(self._table)
        self.env.cr.execute(SQL("""
        CREATE TABLE IF NOT EXISTS %(table)s (
            id serial primary key,
            name varchar not null,
            user_id integer not null REFERENCES res_users(id) ON DELETE CASCADE,
            scope varchar,
            expiration_date timestamp without time zone,
            index varchar(%(index_size)s) not null CHECK (char_length(index) = %(index_size)s),
            key varchar not null,
            create_date timestamp without time zone DEFAULT (now() at time zone 'utc')
        )
        """, table=table, index_size=INDEX_SIZE))

        index_name = self._table + "_user_id_index_idx"
        if len(index_name) > 63:
            # unique determinist index name
            index_name = self._table[:50] + "_idx_" + sha256(self._table.encode()).hexdigest()[:8]
        self.env.cr.execute(SQL(
            "CREATE INDEX IF NOT EXISTS %s ON %s (user_id, index)",
            SQL.identifier(index_name),
            table,
        ))

    @check_identity
    def remove(self):
        return self._remove()

    def _remove(self):
        """Use the remove() method to remove an API Key. This method implement logic,
        but won't check the identity (mainly used to remove trusted devices)"""
        if not self:
            return {'type': 'ir.actions.act_window_close'}
        if self.env.is_system() or self.mapped('user_id') == self.env.user:
            ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'
            _logger.info("API key(s) removed: scope: <%s> for '%s' (#%s) from %s",
               self.mapped('scope'), self.env.user.login, self.env.uid, ip)
            self.sudo().unlink()
            self.env.transaction.invalidate_ormcache()
            return {'type': 'ir.actions.act_window_close'}
        raise AccessError(_("You can not remove API keys unless they're yours or you are a system user"))

    def _check_credentials(self, *, scope, key):
        return _check_apikey_credentials(self.env.cr, scope=scope, key=key, table=self._table)

    def _check_expiration_date(self, date):
        # To be in a sudoed environment or to be an administrator
        # to create a persistent key (no expiration date) or
        # to exceed the maximum duration determined by the user's privileges.
        if self.env.is_system():
            return
        if not date:
            raise ValidationError(_("The API key must have an expiration date"))
        max_duration = max(group.api_key_duration for group in self.env.user.all_group_ids) or 1.0
        if date > datetime.datetime.now() + datetime.timedelta(days=max_duration):
            raise ValidationError(_("You cannot exceed %(duration)s days.", duration=max_duration))
        if date <= datetime.datetime.now():
            raise ValidationError(_("You cannot set an expiration date in the past."))

    def _generate(self, scope, name, expiration_date):
        """Generates an api key.
        :param str scope: the scope of the key.
        :param str name: the name of the key, mainly intended to be displayed in the UI.
        :param datetime.datetime expiration_date: the expiration date of the key.
        :returns: the key.
        :rtype: str

        Note:
        This method must be called in sudo to use a duration
        greater than that allowed by the user's privileges.
        For a persistent key (infinite duration), no value for expiration date.
        """
        self._check_expiration_date(expiration_date)
        # no need to clear the LRU when *adding* a key, only when removing
        k = binascii.hexlify(os.urandom(API_KEY_SIZE)).decode()
        self.env.cr.execute(SQL("""
            INSERT INTO %s (name, user_id, scope, expiration_date, key, index)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            SQL.identifier(self._table),
            name, self.env.user.id, scope, expiration_date or None, KEY_CRYPT_CONTEXT.hash(k), k[:INDEX_SIZE]
        ))

        ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'
        _logger.info("%s generated: scope: <%s> for '%s' (#%s) from %s",
            self._description, scope, self.env.user.login, self.env.uid, ip)

        return k

    def _ensure_can_manage_keys_programmatically(self):
        # Administrators would not be restricted by the ICP check alone,
        # as they could temporarily enable the setting via set_bool().
        # However, this is considered bad practice because it would create a time window
        # where anyone could manage API keys programmatically.
        # Additionally, the enable / call / restore process involves three distinct calls,
        # which is not atomic and prone to errors (e.g., server unavailability during restore),
        # potentially leaving the configuration enabled for all users.
        # To avoid this, an exception is made for Administrators.
        # However, if programmatic API key management were to be enabled by default,
        # this exception should be removed, as disabling the feature should be global.
        ICP = self.env['ir.config_parameter'].sudo()
        programmatic_api_keys_enabled = str2bool(ICP.get_bool('base.enable_programmatic_api_keys'), False)
        if not (self.env.is_system() or programmatic_api_keys_enabled):
            raise UserError(_("Programmatic API keys are not enabled"))

    @api.model
    def generate(self, key, scope, name, expiration_date):
        """
        Generate a new API key with an existing API key.
        The provided `key` must be an existing API key that belongs to the current user.
        Its scope must be compatible with `scope`.
        The `expiration_date` must be allowed for the user's group.

        To renew a key, generate the new one, store it, and then call `revoke` on the previous one.

        :param str key: an active API key belonging to the current user
        :param str scope: the scope of the key.
        :param str name: the name of the key, mainly intended to be displayed in the UI.
        :param str|datetime.datetime expiration_date: the expiration date of the key. String values
            may be either ISO 8601 dates (``"2026-12-30"``) or space-separated datetimes
            (``"2026-12-30 14:30:00"``).
        :returns: the key.
        :rtype: str
        """
        self._ensure_can_manage_keys_programmatically()

        with self.env['res.users']._assert_can_auth(user=key[:INDEX_SIZE]):
            if not isinstance(expiration_date, datetime.datetime):
                expiration_date = fields.Datetime.from_string(expiration_date)

            nb_keys = self.search_count([('user_id', '=', self.env.uid),
                                         '|', ('expiration_date', '=', False), ('expiration_date', '>=', self.env.cr.now())])
            try:
                ICP = self.env['ir.config_parameter'].sudo()
                nb_keys_limit = int(ICP.get_int('base.programmatic_api_keys_limit', DEFAULT_PROGRAMMATIC_API_KEYS_LIMIT))
            except ValueError:
                _logger.warning("Invalid value for 'base.programmatic_api_keys_limit', using default value.")
                nb_keys_limit = DEFAULT_PROGRAMMATIC_API_KEYS_LIMIT
            if nb_keys >= nb_keys_limit:
                raise UserError(_('Limit of %s API keys is reached for programmatic creation', nb_keys_limit))

            # A key can only generate credentials for its own scope.
            #
            # This is enforced in _check_credentials by validating scope usage,
            # and the validated scope is then reused when calling _generate.

            uid = self.env['res.users.apikeys']._check_credentials(scope=scope, key=key)
            if not uid or uid != self.env.uid:
                raise AccessDenied(_("The provided API key is invalid or does not belong to the current user."))
            new_key = self._generate(scope, name, expiration_date)
            _logger.info("%s %r generated from %r", self._description, new_key[:INDEX_SIZE], key[:INDEX_SIZE])

            return new_key

    @api.model
    def revoke(self, key):
        """
        Revoke an existing API key.
        If it exists, the `key` will be removed from the server.

        :param str key: the API key that has to be revoked
        """
        self._ensure_can_manage_keys_programmatically()
        assert key, "key required"
        with self.env['res.users']._assert_can_auth(user=key[:INDEX_SIZE]):
            self.env.cr.execute(SQL('''
                SELECT id, key
                FROM %(table)s
                WHERE
                    index = %(index)s
                    AND (
                        expiration_date IS NULL OR
                        expiration_date >= now() at time zone 'utc'
                    )
            ''', table=SQL.identifier(self._table), index=key[:INDEX_SIZE]))
            for key_id, current_key in self.env.cr.fetchall():
                if key and KEY_CRYPT_CONTEXT.verify(key, current_key):
                    self.env['res.users.apikeys'].browse(key_id)._remove()
                    return True
            raise AccessDenied(_("The provided API key is invalid."))

    @api.autovacuum
    def _gc_user_apikeys(self):
        self.env.cr.execute(SQL("""
            DELETE FROM %s
            WHERE
                expiration_date IS NOT NULL AND
                expiration_date < now() at time zone 'utc'
        """, SQL.identifier(self._table)))
        _logger.info("GC %r delete %d entries", self._name, self.env.cr.rowcount)


def _check_apikey_credentials(cr, *, scope, key, table='res_users_apikeys'):
    """
    Check an API key.

    :param odoo.sql_db.BaseCursor cr: database cursor
    :param str scope:                 scope of the API key
    :param str key:                   the API key to verify
    :param str|None table:            optional table name
    :returns:                         user_id if key is valid, None otherwise
    :rtype: int|None
    """
    assert scope and key, "scope and key required"
    index = key[:INDEX_SIZE]
    cr.execute(SQL('''
        SELECT user_id, key
        FROM %(table)s INNER JOIN res_users u ON (u.id = user_id)
        WHERE
            u.active and index = %(index)s
            AND scope = %(scope)s
            AND (
                expiration_date IS NULL OR
                expiration_date >= now() at time zone 'utc'
            )
    ''',
    index=index, scope=scope, table=SQL.identifier(table)))
    for user_id, current_key in cr.fetchall():
        if key and KEY_CRYPT_CONTEXT.verify(key, current_key):
            return user_id


class ResUsersApikeysDescription(models.TransientModel):
    _name = 'res.users.apikeys.description'
    _description = 'API Key Description'

    def _selection_duration(self):
        # duration value is a string representing the number of days.
        durations = [
            ('1', '1 Day'),
            ('30', '1 Month'),
            ('365', '1 Year'),
        ]
        persistent_duration = ('0', 'Never')  # Magic value to detect an infinite duration
        if self.env.is_system():
            return durations + [persistent_duration]
        max_duration = max(group.api_key_duration for group in self.env.user.all_group_ids) or 1.0
        return list(filter(
            lambda duration: int(duration[0]) <= max_duration, durations
        ))

    def _default_duration(self):
        # Default to 1 month ('30') if that duration is available for the user's group,
        # otherwise fall back to the shortest available duration (the first option).
        selection = self._selection_duration()
        return '30' if '30' in dict(selection) else selection[0][0]

    name = fields.Char("Description", required=True)
    scope = fields.Selection(
        [('rpc', 'RPC')],
        help="""
        A token with scope 'A' can only be used for endpoints requiring a bearer token of scope 'A' and
        can't be used for endpoints requiring any other scope than 'A'.
        """,
        string='Scope',
        required=True,
        default='rpc',
    )
    available_scopes_count = fields.Integer(compute='_compute_available_scopes_count')
    duration = fields.Selection(
        selection='_selection_duration', string='Duration', required=True,
        default=_default_duration,
    )
    expiration_date = fields.Datetime('Expiration Date', compute='_compute_expiration_date', store=True, readonly=False)

    @api.depends('duration')
    def _compute_expiration_date(self):
        for record in self:
            duration = int(record.duration)
            if duration >= 0:
                record.expiration_date = (
                    fields.Date.today() + datetime.timedelta(days=duration)
                    if int(record.duration)
                    else None
                )

    @api.depends('scope')
    def _compute_available_scopes_count(self):
        selection_values = self._fields['scope'].get_values(self.env)
        for record in self:
            record.available_scopes_count = len(selection_values)

    @api.onchange('expiration_date')
    def _onchange_expiration_date(self):
        try:
            self.env['res.users.apikeys']._check_expiration_date(self.expiration_date)
        except UserError as error:
            warning = {
                'type': 'notification',
                'title': _('The API key duration is not correct.'),
                'message': error.args[0]
            }
            return {'warning': warning}

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        self.env['res.users.apikeys']._check_expiration_date(res.expiration_date)
        return res

    @check_identity
    def make_key(self):
        # only create keys for users who can delete their keys
        self.check_access_make_key()

        description = self.sudo()
        k = self.env['res.users.apikeys']._generate(description.scope, description.name, self.expiration_date)
        scope = description.scope
        base_url = ((request and request.httprequest.url_root) or "<Your URL>").rstrip('/')
        description.unlink()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users.apikeys.show',
            'name': self.env._('Save your API Key'),
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_key': k,
                'default_scope': scope,
                'default_base_url': base_url,
            },
        }

    def check_access_make_key(self):
        if not self.env.user._is_internal():
            raise AccessError(_("Only internal users can create API keys"))


class ResUsersApikeysShow(models.Model):
    _name = 'res.users.apikeys.show'
    _description = 'Show API Key'
    _auto = False  # no table
    _table_sql = SQL('(0)')

    # the field 'id' is necessary for the onchange that returns the value of 'key'
    id = fields.Id()
    key = fields.Char(readonly=True)
    scope = fields.Char(readonly=True)
    base_url = fields.Char(readonly=True)

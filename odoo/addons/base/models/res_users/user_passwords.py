# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The passwords of the users: their setting, their encryption and their changes."""

from __future__ import annotations

from odoo import _
from odoo.exceptions import AccessDenied, UserError
from .crypt import CryptContext, MIN_ROUNDS


def _set_password(self):
    ctx = self._crypt_context()
    for user in self:
        self._set_encrypted_password(user.id, ctx.hash(user.password))


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


def action_change_password_wizard(self):
    return {
        'type': 'ir.actions.act_window',
        'target': 'new',
        'res_model': 'change.password.wizard',
        'view_mode': 'form',
        'name': 'Change Password',
        'context': {'active_ids': self.ids, 'active_model': 'res.users'}
    }


def preference_change_password(self):
    return {
        'type': 'ir.actions.act_window',
        'target': 'new',
        'res_model': 'change.password.own',
        'view_mode': 'form',
    }


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

# Part of Odoo. See LICENSE file for full copyright and licensing details.

# timeout extends the trusted device model defined by totp, so it is imported after totp and totp_mail.
from . import totp, totp_mail
from . import passkey, passkey_portal, password_policy, password_policy_portal, password_policy_signup, timeout

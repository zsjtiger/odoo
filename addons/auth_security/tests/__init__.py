# Part of Odoo. See LICENSE file for full copyright and licensing details.

from .passkey import test_passkey_demo as test_passkey_passkey_demo
from .passkey_portal import test_passkey_portal as test_passkey_portal_passkey_portal
from .timeout import test_auth_timeout as test_timeout_auth_timeout
from .totp import test_apikeys as test_totp_apikeys
from .totp import test_totp as test_totp_totp
from .totp_mail import test_auth_signup as test_totp_mail_auth_signup
from .totp_mail import test_notify_security_update_totp as test_totp_mail_notify_security_update_totp
from .totp_mail import test_totp as test_totp_mail_totp

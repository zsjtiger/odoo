# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Authentication: Security (Passkeys, Password Policy, TOTP, Timeout)',
    'summary': 'Passkeys, password policy, two-factor authentication (TOTP) and session timeout',
    'version': '1.1',
    'category': 'Hidden/Tools',
    'license': 'LGPL-3',
    'author': 'Odoo S.A.',
    'depends': ['base_setup', 'web', 'portal', 'auth_signup', 'bus', 'mail'],
    'data': ['passkey/views/auth_passkey_key_views.xml', 'passkey/views/auth_passkey_login_templates.xml', 'passkey/views/res_users_identitycheck_views.xml', 'passkey/views/res_users_views.xml', 'passkey/security/ir.access.csv', 'passkey_portal/views/templates.xml', 'password_policy/data/defaults.xml', 'password_policy/views/res_users.xml', 'password_policy/views/res_config_settings_views.xml', 'password_policy_portal/views/templates.xml', 'password_policy_signup/views/signup_templates.xml', 'timeout/views/res_groups_views.xml', 'totp/data/ir_action_data.xml', 'totp/views/res_users_views.xml', 'totp/views/templates.xml', 'totp/wizard/auth_totp_wizard_views.xml', 'totp/security/ir.access.csv', 'totp_mail/data/ir_action_data.xml', 'totp_mail/data/mail_template_data.xml', 'totp_mail/data/security_notifications_template.xml', 'totp_mail/views/res_config_settings_views.xml', 'totp_mail/views/res_users_views.xml', 'totp_mail/views/templates.xml'],
    'assets': {
        'web.assets_backend': ['auth_security/static/lib/passkey/simplewebauthn.js', 'auth_security/static/src/passkey/services/check_identity/*', 'auth_security/static/src/passkey/views/*', 'auth_security/static/src/passkey/scss/res_users.scss', 'auth_security/static/src/password_policy/**/*', ('remove', 'auth_security/static/src/password_policy/css/password_field.css'), 'auth_security/static/src/timeout/services/check_identity/*', 'auth_security/static/src/totp/scss/**/*', 'auth_security/static/src/totp/services/check_identity/*', 'auth_security/static/src/totp_mail/services/check_identity/*'],
        'web.assets_frontend': ['auth_security/static/lib/passkey/simplewebauthn.js', 'auth_security/static/src/passkey/interactions/*', 'auth_security/static/src/passkey/services/check_identity/*', 'auth_security/static/src/passkey_portal/**', 'auth_security/static/src/password_policy/css/password_field.css', 'auth_security/static/src/password_policy/password_policy.js', 'auth_security/static/src/password_policy_signup/public/**/*', 'auth_security/static/src/password_policy/password_meter.js', 'auth_security/static/src/password_policy/password_policy.js', 'auth_security/static/src/timeout/services/check_identity/*', 'auth_security/static/src/totp/services/check_identity/*', 'auth_security/static/src/totp_mail/services/check_identity/*'],
        'web.assets_tests': ['auth_security/static/tests/passkey/*.js', 'auth_security/static/tests/passkey_portal/tours/*.js', 'auth_security/static/tests/timeout/tours/**/*', 'auth_security/static/tests/totp/**/*', 'auth_security/static/tests/totp_mail/**/*'],
    },
    'installable': True,
    'application': False,
}

# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Authentication: External Providers (OAuth, LDAP)',
    'summary': 'Sign in with OAuth providers and LDAP directories',
    'category': 'Hidden/Tools',
    'license': 'LGPL-3',
    'author': 'Odoo S.A.',
    'depends': [
        'base',
        'web',
        'base_setup',
        'auth_signup',
    ],
    'external_dependencies': {'python': ['python-ldap']},
    'data': [
        # oauth
        'oauth/data/auth_oauth_data.xml',
        'oauth/views/auth_oauth_views.xml',
        'oauth/views/res_config_settings_views.xml',
        'oauth/views/auth_oauth_templates.xml',
        'oauth/security/ir.access.csv',
        # ldap
        'ldap/views/ldap_installer_views.xml',
        'ldap/views/res_config_settings_views.xml',
        'ldap/security/ir.access.csv',
    ],
    'assets': {
        'web.assets_frontend': [
            'auth_external/static/src/oauth/**/*',
        ],
    },
    'installable': True,
    'application': False,
}

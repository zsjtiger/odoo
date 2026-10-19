# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': "Studio",
    'summary': "Create and customize your Odoo apps",
    'website': 'https://www.odoo.com/app/studio',
    'description': """
Studio - Customize Odoo
=======================

This addon allows the user to customize most element of the user interface, in a
simple and graphical way. It has two main features:

* create a new application (add module, top level menu item, and default action)
* customize an existing application (edit menus, actions, views, translations, ...)

Note: Only the admin user is allowed to make those customizations.
""",
    'category': 'Customizations/Studio',
    'sequence': 75,
    'depends': [
        'base_automation',
        'mail',
        'html_editor',
        'web_enterprise',
    ],
    'data': [
        'views/assets.xml',
        'views/actions.xml',
        'views/studio_menus.xml',
        'views/ir_actions_report_xml.xml',
        'views/ir_model_data.xml',
        'views/base_automation_views.xml',
        'views/studio_approval_views.xml',
        'views/reset_view_arch_wizard.xml',
        'views/studio_export_wizard_views.xml',
        'views/studio_export_model_views.xml',
        'data/mail_templates.xml',
        'data/web_tour_tour.xml',
        'wizard/base_module_uninstall_view.xml',
        'security/ir.access.csv',
    ],
    'application': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'assets': {
        'web.assets_backend': [
            'web_builder/static/src/systray_item/**/*.js',
            'web_builder/static/src/studio_service.js',
            'web_builder/static/src/utils.js',

            'web_builder/static/src/client_action/studio_action_loader.js',
            'web_builder/static/src/app_creation/app_creator/app_creator_shortcut.js',
            'web_builder/static/src/client_action/components/**/*.js',
            'web_builder/static/src/client_action/components/**/*.xml',
            'web_builder/static/src/export/**/*.js',
            'web_builder/static/src/home_menu/background.js',
            'web_builder/static/src/views/**/*.js',
            'web_builder/static/src/js/**/*.js',
            ('remove', 'web_builder/static/src/views/kanban_report/**/*'),
            'web_builder/static/src/approval/**/*',
            'web_builder/static/src/**/*.xml',
            'web_builder/static/src/editors/report_editor/qweb_table_plugin.scss',
        ],
        # This bundle is lazy loaded: it is loaded when studio is opened for the first time
        'web_builder.studio_assets': [
            ('include', 'web.assets_backend_lazy'),
            ('include', 'web_builder.studio_assets_minimal'),
        ],
        'web_builder.studio_assets_minimal': [
            'html_editor/static/src/main/media/media_dialog/icon_selector.js',
            'web_builder/static/src/client_action/**/*.js',
            'web_builder/static/src/editors/**/*.js',
            'web_builder/static/src/app_creation/**/*.js',
            'web_builder/static/src/home_menu/studio/**/*.js',
            'web_builder/static/src/views/kanban_report/**/*.js',
            ('remove', 'web_builder/static/src/client_action/studio_action_loader.js'),
            ('remove', 'web_builder/static/src/app_creation/app_creator/app_creator_shortcut.js'),

            ('include', 'web._assets_helpers'),
            'web_builder/static/src/scss/bootstrap_overridden.scss',
            'web/static/src/scss/variables/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            'web_builder/static/src/client_action/variables.scss',
            'web_builder/static/src/client_action/**/*.scss',
            'web_builder/static/src/editors/**/*.scss',
            'web_builder/static/src/app_creation/**/*.scss',
            'web_builder/static/src/home_menu/studio/**/*.scss',
            ("remove", "web_builder/static/src/editors/report_editor/report_iframe.scss"),
            'web_builder/static/src/views/kanban_report/**/*.scss',
        ],
        "web_builder.studio_assets_dark": [
            'web_builder/static/src/client_action/variables.dark.scss',
            ('include', 'web.assets_backend_lazy_dark'),
            ('include', 'web_builder.studio_assets_minimal'),
        ],
        'web.assets_tests': [
            'web_builder/static/tests/tours/**/*',
        ],
        'web_builder.report_assets': [
            ('include', 'web._assets_helpers'),
            'web/static/src/scss/variables/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            "web/static/src/webclient/actions/reports/report.scss",
            'web_builder/static/src/editors/report_editor/report_iframe.scss',
            'web_builder/static/src/editors/report_editor/qweb_table_plugin.scss',
            'html_editor/static/src/main/selection_placeholder_plugin.scss',
        ],
        'web.assets_unit_tests': [
            ('include', 'web_builder.studio_assets_minimal'),
            'web_builder/static/tests/**/*',
            ('remove', 'web_builder/static/tests/legacy/**/*'),
            ('remove', 'web_builder/static/tests/tours/**/*'),
        ],
    }
}

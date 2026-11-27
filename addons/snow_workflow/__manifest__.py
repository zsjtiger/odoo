# -*- coding: utf-8 -*-
{
    'name': "snow_workflow",

    'summary': """
    """,
    'author': "CrossNow",
    'website': "http://www.crossnow.cn",
    'category': 'snow',
    'version': '1.0',
    'depends': ['base', 'web'],
    'data': [
        'security/ir_model_access.xml',
        'views/approved_view.xml',
        'views/copy_to_me.xml',
        'views/my_submission_view.xml',
        'views/pending_my_approval_view.xml',
        'views/workflow_definition_views.xml',
        'views/workflow_warning_view.xml',
        'views/workflow_menu.xml',
        'wizard/workflow_attendee_selection.xml',
        'data/config.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'snow_workflow/static/src/fields/**/*.js',
            'snow_workflow/static/src/views/**/*.js',
            'snow_workflow/static/src/designer/**/*.js',
            'snow_workflow/static/src/designer/**/*.scss',
            'snow_workflow/static/src/scss/*.scss',
        ],
        'web.assets_unit_tests': [
            'snow_workflow/static/src/fields/**/*.js',
            'snow_workflow/static/src/views/**/*.js',
            'snow_workflow/static/src/designer/**/*.js',
            'snow_workflow/static/tests/**/*.test.js',
        ],
    },
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': True,
}

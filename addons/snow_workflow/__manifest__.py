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
        'data/config.xml'
    ],
    'assets': {
        'web.assets_backend': [
            # 旧版 (odoo.define / web.field_registry) 的 JS 暂未迁移到 Owl, 不加载, 见 static/src/js
            'snow_workflow/static/src/scss/*.scss',
            # 旧版 qweb 资源包已不存在: 模板与 JS 一起由 web.assets_backend 加载
            'snow_workflow/static/src/xml/*.xml',
        ],
        'web.assets_frontend': [
            # '/static/src/js/position_advance_query_panel.js',
        ],
    },
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': True,
}

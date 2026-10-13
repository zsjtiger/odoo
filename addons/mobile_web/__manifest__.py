# -*- coding: utf-8 -*-
{
    'name': "Mobile Web",
    'category': 'Hidden',
    'description': """
Odoo Mobile Web core module
============================

This module provides the core of the Odoo Mobile Web Client.
    """,
    'version': '1.0',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.access.csv',

        ## data: page and navigation configuration, kept when upgrading
        'data/mobile_pages.xml',

        ## views: templates
        'views/templates/base_layout.xml',
        'views/templates/login_page.xml',
        'views/templates/webclient_bootstrap.xml',
    ],
    'assets': {
        # 登录前要加载的
        'mobile_web.assets_frontend': [
            # 模块加载器与 owl(common包依赖 odoo.define 与 @odoo/owl)
            'web/static/src/boot/module_loader.js',
            'web/static/lib/luxon/luxon.js',
            'web/static/lib/owl/owl.js',
            'web/static/src/core/owl/owl3_compatibility_layer.js',
            'web/static/src/core/owl/utils.js',
            'web/static/lib/owl/odoo_module.js',
            # 第三方库(UMD, 注册为全局 CryptoJS)
            'mobile_web/static/lib/crypto-js/crypto-js.js',
            # common包
            'mobile_web/static/src/common/**/*',
            # 页面包(仅加载登录页)
            'mobile_web/static/src/pages/login/**/*',
        ],

        # 登录后要加载的
        'mobile_web.assets_backend': [
            # web core js only
            ('include', 'mobile_web._assets_load_web_core_js'),
            # mobile core包
            "mobile_web/static/src/core/**/*",
            # common包
            'mobile_web/static/src/common/**/*',
            # webclient结构包
            'mobile_web/static/src/webclient/**/*',
            # 页面包(去掉登录页)
            'mobile_web/static/src/pages/**/*',
            ('remove', 'mobile_web/static/src/pages/login/**/*'),
        ],

        # WebClient bootstrap专用
        'mobile_web.assets_web': [
            ('include', 'mobile_web.assets_backend'),
            'mobile_web/static/src/start.js',
            'mobile_web/static/src/main.js'
        ],

        'mobile_web._assets_load_web_core_js': [
            # module loader
            'web/static/src/boot/module_loader.js',
            # libs
            'web/static/lib/luxon/luxon.js',
            'web/static/lib/owl/owl.js',
            'web/static/lib/owl/odoo_module.js',
            # core
            'web/static/src/boot/env.js',
            'web/static/src/boot/session.js',
            'web/static/src/core/**/*.js',
            ('remove', 'web/static/src/core/components/emoji_picker/emoji_data.js'), #TODO: always lazy-loaded
        ]
    },
    'pre_init_hook': '_pre_init_hook',
    'post_init_hook': '_post_init_hook',
    'uninstall_hook': '_uninstall_hook',
}

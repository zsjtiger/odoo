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
            ('include', 'mobile_web._assets_load_loader_js'),
            # 第三方库(UMD, 注册为全局 CryptoJS)
            'mobile_web/static/lib/crypto-js/crypto-js.js',
            # common包
            'mobile_web/static/src/common/**/*',
            # 页面包(仅加载登录页)
            'mobile_web/static/src/pages/login/**/*',
        ],

        # 启动基础(JS): 模块加载器, owl, env, session. 必须先于 web 的 JS 加载
        'mobile_web.assets_boot': [
            ('include', 'mobile_web._assets_load_loader_js'),
            # core
            'web/static/src/boot/session.js',
        ],

        # 登录后要加载的移动端代码(css+js). 依赖的 web 模块由 web.assets_backend 提供,
        # 因此必须在 web 的 JS 之后加载, 模板中的顺序: boot -> web -> 本包 -> start
        'mobile_web.assets_backend': [
            # mobile core包(core/** 由 web 提供, 这里只保留移动端的 router)
            'mobile_web/static/src/core/browser/router.js',
            # common包
            'mobile_web/static/src/common/**/*',
            # webclient结构包
            'mobile_web/static/src/webclient/**/*',
            # 页面包(去掉登录页)
            'mobile_web/static/src/pages/**/*',
            ('remove', 'mobile_web/static/src/pages/login/**/*'),
        ],

        # 挂载入口: 必须在 web.assets_backend 之后加载
        'mobile_web.assets_start': [
            # env 依赖 web 的核心服务, 因此放在 web 的 JS 之后
            'web/static/src/boot/env.js',
            'web/static/src/boot/start.js',
            'mobile_web/static/src/main.js',
        ],

        # 模块加载器与 owl, 登录页与启动包共用(不含 session, 登录页没有 session 信息)
        'mobile_web._assets_load_loader_js': [
            # module loader
            'web/static/src/boot/module_loader.js',
            # libs
            'web/static/lib/luxon/luxon.js',
            'web/static/lib/owl/owl.js',
            'web/static/lib/owl/odoo_module.js',
            # owl 兼容层(供 @web/core/owl/utils 使用)
            'web/static/src/core/owl/owl3_compatibility_layer.js',
            'web/static/src/core/owl/utils.js',
        ]
    },
    'pre_init_hook': '_pre_init_hook',
    'post_init_hook': '_post_init_hook',
    'uninstall_hook': '_uninstall_hook',
}

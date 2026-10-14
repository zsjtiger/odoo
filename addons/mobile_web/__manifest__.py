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

        ## views: 列表/看板的标题字段配置(继承 web 的视图, 只加 title 属性)
        'data/mobile_views.xml',

        ## views: templates
        'views/templates/base_layout.xml',
        'views/templates/login_page.xml',
        'views/templates/webclient_bootstrap.xml',
    ],
    'assets': {
        # 登录前要加载的
        'mobile_web.assets_frontend': [
            # 模块加载器与 owl(common包依赖 odoo.define 与 @odoo/owl)
            ('include', 'mobile_web._assets_load_owl_js'),
            # 第三方库(UMD, 注册为全局 CryptoJS)
            'mobile_web/static/lib/crypto-js/crypto-js.js',
            # common包
            'mobile_web/static/src/common/**/*',
            # 页面包(仅加载登录页)
            'mobile_web/static/src/pages/login/**/*',
        ],

        # 启动基础(JS): 模块加载器, owl, env, session. 必须先于 web 的 JS 加载
        'mobile_web.assets_boot': [
            ('include', 'mobile_web._assets_load_owl_js'),
            # luxon 只在后台使用(登录页不需要)
            ('include', 'mobile_web._assets_load_luxon_js'),
            # core
            'web/static/src/boot/session.js',
        ],

        # 登录后要加载的移动端代码(css+js). 依赖的 web 模块由 web.assets_backend 提供,
        # 因此必须在 web 的 JS 之后加载, 模板中的顺序: boot -> web -> 本包 -> start
        # web 后台包的移动端版本: 去掉移动端不用的桌面端部分(日历/设置视图, 桌面端外壳, 教程).
        # 不改动 web.assets_backend 本身, 桌面端不受影响
        'mobile_web.assets_web_backend': [
            ('include', 'web.assets_backend'),
            # 视图: 移动端只支持 list / kanban / form
            ('remove', 'web/static/src/views/calendar/**'),
            ('remove', 'web/static/src/views/settings/**'),
            # 桌面端外壳(移动端有自己的 webclient 与 navbar)
            # 注意: webclient/navbar 与 webclient/menus 不能删, 它们的 scss 是移动端布局需要的;
            # webclient/actions 不能删, action 服务依赖它(menu、reloadCompany 等服务需要 action)
            ('remove', 'web/static/src/webclient/webclient.js'),
            ('remove', 'web/static/src/webclient/user_menu/**'),
            ('remove', 'web/static/src/webclient/burger_menu/**'),
            ('remove', 'web/static/src/webclient/switch_company_menu/**'),
            ('remove', 'web/static/src/webclient/share_target/**'),
            ('remove', 'web/static/src/webclient/offline_systray/**'),
            ('remove', 'web/static/src/webclient/debug/**'),
            ('remove', 'web/static/src/views/debug_items.js'),
            # 教程(web_tour) 移动端不使用
            ('remove', 'web_tour/static/src/**'),
        ],

        'mobile_web.assets_backend': [
            # mobile core包(core/** 由 web 提供, 这里只保留移动端的 router)
            'mobile_web/static/src/core/browser/router.js',
            # common包
            'mobile_web/static/src/common/**/*',
            # webclient结构包
            'mobile_web/static/src/webclient/**/*',
            # 移动端视图层(list / kanban / form / 字段)
            'mobile_web/static/src/views/**/*',
            # 页面包(去掉登录页)
            'mobile_web/static/src/pages/**/*',
            ('remove', 'mobile_web/static/src/pages/login/**/*'),
        ],

        # 挂载入口: 必须在 web.assets_backend 之后加载
        # 单元测试(hoot): 移动端的源码与测试文件, 由 web 的测试包统一运行, 测试标签为 mobile
        'web.assets_unit_tests': [
            ('include', 'mobile_web.assets_unit_src'),
            'mobile_web/static/tests/helpers/*.js',
            'mobile_web/static/tests/*.test.js',
        ],
        # 单元测试覆盖的移动端源码; main.js 会启动整个 webclient, 不放入测试包
        'mobile_web.assets_unit_src': [
            'mobile_web/static/src/common/**/*.js',
            'mobile_web/static/src/core/browser/router.js',
            'mobile_web/static/src/webclient/**/*.js',
            'mobile_web/static/src/views/**/*.js',
            'mobile_web/static/src/pages/**/*.js',
        ],
        'mobile_web.assets_start': [
            # env 依赖 web 的核心服务, 因此放在 web 的 JS 之后
            'web/static/src/boot/env.js',
            'web/static/src/boot/start.js',
            'mobile_web/static/src/main.js',
        ],

        # 模块加载器与 owl, 登录页与启动包共用(不含 session, 登录页没有 session 信息)
        'mobile_web._assets_load_owl_js': [
            # module loader
            'web/static/src/boot/module_loader.js',
            # libs
            'web/static/lib/owl/owl.js',
            'web/static/lib/owl/odoo_module.js',
            # owl 兼容层(供 @web/core/owl/utils 使用)
            'web/static/src/core/owl/owl3_compatibility_layer.js',
            'web/static/src/core/owl/utils.js',
        ],
        'mobile_web._assets_load_luxon_js': [
            'web/static/lib/luxon/luxon.js',
        ]
    },
    'pre_init_hook': '_pre_init_hook',
    'post_init_hook': '_post_init_hook',
    'uninstall_hook': '_uninstall_hook',
}

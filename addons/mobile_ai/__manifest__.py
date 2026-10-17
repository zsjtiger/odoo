# -*- coding: utf-8 -*-
{
    'name': "Mobile AI",
    'category': 'Hidden',
    'summary': "AI assistant in the Odoo Mobile Web client",
    'description': """
Mobile AI
=========

Adds the AI assistant to the mobile web client. The chat is the same discuss channel and
AI session as in the web client, so conversations and tools behave the same and are shared
between both clients.
    """,
    'version': '1.0',
    'depends': ['mobile_web', 'ai'],
    'data': [
        'data/mobile_ai_pages.xml',
    ],
    'assets': {
        # mobile_web 的移动端包移除了桌面端的一些资源(表情选择器、日历视图等), 但 mail 与 ai 的
        # 前端代码依赖它们. 安装 ai 时在这里补回, 否则移动端无法启动(mail.store 等服务缺失).
        'mobile_web.assets_web_backend': [
            'web/static/src/core/components/emoji_picker/**/*',
            'web/static/src/views/calendar/**/*',
        ],
        'mobile_web.assets_backend': [
            'mobile_ai/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'mobile_ai/static/src/**/*.js',
            'mobile_ai/static/tests/**/*.test.js',
        ],
    },
    'license': 'LGPL-3',
}

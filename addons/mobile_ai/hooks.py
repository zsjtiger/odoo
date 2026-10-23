# -*- coding: utf-8 -*-

# 标签顺序: AI 在"我的"之前, "我的"始终是最后一个
AI_TAB_SEQUENCE = 4
ME_TAB_SEQUENCE = 5

def _post_init_hook(env):
    set_tab_sequences(env)

def set_tab_sequences(env):
    """ 设置标签栏顺序. mobile_web 的标签数据是 noupdate 的, 因此由钩子/迁移脚本调整 """
    Tab = env['mobile_web.mobile.page.actions']
    Tab.search([('ir_action', '=', env.ref('mobile_ai.ai_page_action').id)]).write({'sequence': AI_TAB_SEQUENCE})
    Tab.search([('ir_action', '=', env.ref('mobile_web.user_my_page_action').id)]).write({'sequence': ME_TAB_SEQUENCE})

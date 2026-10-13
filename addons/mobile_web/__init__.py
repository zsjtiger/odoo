# -*- coding: utf-8 -*-

from . import controllers
from . import models
from . import tests


# 安装模块前的hooks, 使用sql创建 `ir_act_mobile_page` 与 `ir_actions` 之间的inherit关系
# 使用 IF NOT EXISTS, 保证表已存在时(例如重新安装)不会报错
def _pre_init_hook(env):
    env.cr.execute("CREATE TABLE IF NOT EXISTS ir_act_mobile_page (primary key(id)) INHERITS (ir_actions);")


# 安装后检查: 页面组件id若不在前端注册表中, 页面不会显示, 只记录日志, 不阻止安装(管理员可能自行添加页面)
def _post_init_hook(env):
    from .models.mobile_page import PAGE_COMPONENT_IDS  # noqa: PLC0415
    pages = env['mobile_web.mobile.page'].search([])
    unknown = pages.filtered(lambda p: p.page_component_id not in PAGE_COMPONENT_IDS)
    if unknown:
        import logging  # noqa: PLC0415
        logging.getLogger(__name__).warning(
            "mobile pages without a registered frontend component: %s", unknown.mapped('page_component_id'))


# 卸载模块后的hook: 删除由 `_pre_init_hook` 创建的表
def _uninstall_hook(env):
    env.cr.execute("DROP TABLE IF EXISTS ir_act_mobile_page;")

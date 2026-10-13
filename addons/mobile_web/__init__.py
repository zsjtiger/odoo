# -*- coding: utf-8 -*-

from . import controllers
from . import models


# 安装模块前的hooks, 使用sql创建 `ir_act_mobile_page` 与 `ir_actions` 之间的inherit关系
# 使用 IF NOT EXISTS, 保证表已存在时(例如重新安装)不会报错
def _pre_init_hook(env):
    env.cr.execute("CREATE TABLE IF NOT EXISTS ir_act_mobile_page (primary key(id)) INHERITS (ir_actions);")


# 卸载模块后的hook: 删除由 `_pre_init_hook` 创建的表
def _uninstall_hook(env):
    env.cr.execute("DROP TABLE IF EXISTS ir_act_mobile_page;")

# -*- coding: utf-8 -*-

from . import controllers
from . import models


# 安装模块前的hooks, 使用sql创建 `ir_act_mobile_page`` 与 `ir_actions` 之间的inherit关系
def _pre_init_hook(env):
    env.cr.execute("CREATE TABLE ir_act_mobile_page (primary key(id)) INHERITS (ir_actions);")

# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api

from odoo.addons.mobile_ai.hooks import set_tab_sequences


def migrate(cr, version):
    """ 安装过旧版本的数据库: AI 排在"我的"之前, "我的"保持在最后 """
    env = api.Environment(cr, SUPERUSER_ID, {})
    set_tab_sequences(env)

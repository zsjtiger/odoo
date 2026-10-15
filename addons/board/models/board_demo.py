# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class BoardDemo(models.Model):
    """演示模型: 每个图表字段保存 JSON 数据, 由对应的仪表盘字段组件绘制."""
    _name = 'board.demo'
    _description = "Board Chart Demo"

    name = fields.Char(required=True)
    chart_bar = fields.Text(string="Bar")
    chart_line = fields.Text(string="Line")
    chart_pie = fields.Text(string="Pie")
    chart_gauge = fields.Text(string="Gauge")
    chart_radar = fields.Text(string="Radar")
    chart_card = fields.Text(string="Card")

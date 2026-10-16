# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class BoardDemo(models.Model):
    """演示模型: 每个图表字段保存 JSON 数据, 由对应的仪表盘字段组件绘制."""
    _name = 'reporting.demo'
    _description = "Board Chart Demo"

    name = fields.Char(required=True)
    chart_bar = fields.Text(string="Bar")
    chart_line = fields.Text(string="Line")
    chart_pie = fields.Text(string="Pie")
    chart_gauge = fields.Text(string="Gauge")
    chart_radar = fields.Text(string="Radar")
    chart_card = fields.Text(string="Card")
    chart_doughnut = fields.Text(string="Doughnut")
    chart_doughnut_rounded = fields.Text(string="Rounded Doughnut")
    chart_doughnut_half = fields.Text(string="Half Doughnut")
    chart_pie_pad = fields.Text(string="Pie Pad Angle")
    chart_scatter = fields.Text(string="Scatter")
    chart_scatter_quartet = fields.Text(string="Scatter Quartet")
    chart_scatter_cluster = fields.Text(string="Scatter Cluster")
    chart_scatter_cluster_process = fields.Text(string="Scatter Cluster Process")
    chart_scatter_regression = fields.Text(string="Scatter Regression")
    chart_scatter_effect = fields.Text(string="Scatter Effect")
    chart_smooth = fields.Text(string="Smooth Line")
    chart_stacked = fields.Text(string="Stacked Line")
    chart_marked = fields.Text(string="Marked Line")
    chart_pie_line = fields.Text(string="Pie and Line")
    chart_polar_radial = fields.Text(string="Polar Radial")
    chart_polar_tangential = fields.Text(string="Polar Tangential")
    chart_polar_end_angle = fields.Text(string="Polar End Angle")
    chart_bar_horizontal = fields.Text(string="Horizontal Bar")
    chart_bar_axis_break = fields.Text(string="Bar Axis Break")
    chart_bar_gradient = fields.Text(string="Gradient Bar")

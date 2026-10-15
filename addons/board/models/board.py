# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

from ..tools.data_convert import SqlDataConvert


class Board(models.AbstractModel):
    _name = 'board.board'
    _description = "Board"
    _auto = False

    # This is necessary for when the web client opens a dashboard. Technically
    # speaking, the dashboard is a form view, and opening it makes the client
    # initialize a dummy record by invoking onchange(). And the latter requires
    # an 'id' field to work properly...
    id = fields.Id()

    @api.model_create_multi
    def create(self, vals_list):
        return self

    @api.model
    def convert_sql_to_board(self, model, all_fields, data, x_field=None):
        """

        :param model:
        :param all_fields:
        :param data:
        :param x_field:
        :return:
        """
        sql_data_convert = SqlDataConvert(self.env, model, all_fields)
        if x_field:
            sql_data_convert.set_x_field(x_field)
        return sql_data_convert.convert(data)

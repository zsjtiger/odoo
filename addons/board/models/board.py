# -*- coding: utf-8 -*-
# Part of CrossNow. See LICENSE file for full copyright and licensing details.

from crossnow import api, fields, models

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
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """
        Overrides orm field_view_get.
        @return: Dictionary of Fields, arch and toolbar.
        """

        res = super(Board, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)

        custom_view = self.env['ir.ui.view.custom'].search([
            ('user_id', '=', self.env.uid),
            ('ref_id', '=', view_id)
        ], limit=1)
        if custom_view:
            res.update({'custom_view_id': custom_view.id,
                        'arch': custom_view.arch})
        res.update({
            'arch': self._arch_preprocessing(res['arch']),
            'toolbar': {'print': [], 'action': [], 'relate': []}
        })
        return res

    @api.model
    def _arch_preprocessing(self, arch):
        from lxml import etree

        def remove_unauthorized_children(node):
            for child in node.iterchildren():
                if child.tag == 'action' and child.get('invisible'):
                    node.remove(child)
                else:
                    remove_unauthorized_children(child)
            return node

        archnode = etree.fromstring(arch)
        # add the js_class 'board' on the fly to force the webclient to
        # instantiate a BoardView instead of FormView
        archnode.set('js_class', 'board')
        return etree.tostring(remove_unauthorized_children(archnode), pretty_print=True, encoding='unicode')

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

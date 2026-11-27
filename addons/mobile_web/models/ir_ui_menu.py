import logging

from odoo import models, fields
from odoo.http import request


_logger = logging.getLogger(__name__)


class MenuMobileExtend(models.Model):
    _inherit = 'ir.ui.menu'

    device_type = fields.Selection(
        selection=[('mobile', 'Mobile'), ('pc', 'PC'), ('both', 'Both')],
        string="Menu Show Device Type",
        default='pc'
    )

    def _filter_visible_menus(self):
        """
        在base的基础上，额外过滤掉不符合当前device_type的menu记录
        """
        base_filtered = super()._filter_visible_menus()

        current_device_type = request.context.get('ir.ui.menu.current_device', None)

        if current_device_type == 'mobile':
            return base_filtered.filtered(lambda menu: menu.device_type == 'mobile' or menu.device_type == 'both')
        elif current_device_type == 'pc':
            return base_filtered.filtered(lambda menu: menu.device_type == 'pc' or menu.device_type == 'both')
        else:
            _logger.warning(
                "current request context: `%s` does not contain key: `ir.ui.menu.current_device`, use default: `pc`",
                request.context
            )
            return base_filtered.filtered(lambda menu: menu.device_type == 'pc' or menu.device_type == 'both')

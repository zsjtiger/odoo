from crossnow import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def load_menus(self, debug):
        """
        判断审批流开关状态，若开关关闭，过滤掉审批流菜单

        :return: 菜单
        """
        menus = super().load_menus(debug)

        if (self.env['ir.config_parameter'].sudo().get_param('enable_common_workflow') != 'enable'
                and not self.env.user.has_group('base.group_erp_manager')):
            target_index = ''
            for index, menu in menus.items():
                if 'xmlid' in menu and menu['xmlid'] == 'snow_workflow.snow_workflow_menu_root':
                    target_index = index
            if target_index in menus['root']['children']:
                menus['root']['children'].remove(target_index)
        return menus

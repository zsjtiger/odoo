from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def fetch_approval_models(self):
        """
        给res.users添加函数，获取用户有审批权限对模块

        :return: 模块列表
        """
        model_access = self.env["ir.access"]
        if 'perm_approval' in model_access._fields:
            # 用当前用户的分组判断, 不依赖调用时的 self 是哪个用户记录
            group_ids = self.env.user.group_ids.ids
            model_access_ids = model_access.search(['&', ('perm_approval', '=', True),
                                                    '|', ('group_id', 'in', group_ids), ('group_id', '=', False)])
            model_names = [access_obj.model_id.model for access_obj in model_access_ids]
            return list(set(model_names))
        else:
            return []

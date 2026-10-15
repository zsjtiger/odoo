from crossnow import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def fetch_approval_models(self):
        """
        给res.users添加函数，获取用户有审批权限对模块

        :return: 模块列表
        """
        model_access = self.env["ir.model.access"]
        if 'perm_approval' in model_access._fields:
            model_access_ids = model_access.search(['&', ('perm_approval', '=', True),
                                                    '|', ('group_id', 'in', self.groups_id.ids), ('group_id', '=', False)])
            model_names = [access_obj.model_id.model for access_obj in model_access_ids]
            return list(set(model_names))
        else:
            return []

from crossnow import models
from crossnow.http import request


class Http(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """
        对ir.http中session_info方法进行扩展，审批流权限加入session

        :return: session信息
        """
        res = super().session_info()
        user = request.env.user
        approval_models = user.fetch_approval_models()
        res.update({"approval_models": approval_models})
        enable_common_workflow = False
        if request.env['ir.config_parameter'].sudo().get_param('enable_common_workflow') != 'disable':
            enable_common_workflow = True
        res.update({"enable_common_workflow": enable_common_workflow})
        return res

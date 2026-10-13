from crossnow import models, fields, api


# TODO: device_type可用于手机端切换view的功能使用
# class ViewMobileExtend(models.Model):
#     _inherit = 'ir.ui.view'
#
#     device_type = fields.Selection(
#         selection=[('mobile', 'Mobile'), ('pc', 'PC'), ('both', 'Both')],
#         string="Menu Show Device Type",
#         default='pc'
#     )

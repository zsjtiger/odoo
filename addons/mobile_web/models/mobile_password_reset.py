import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# 重置链接的有效期, 以及新密码的最小长度 (与登录页的提示一致)
RESET_VALIDITY = timedelta(hours=1)
MIN_PASSWORD_LENGTH = 10


class MobilePasswordReset(models.Model):
    """ 手机端找回密码的一次性令牌: 每个令牌只能使用一次, 并在有效期后失效 """
    _name = 'mobile_web.password.reset'
    _description = 'Mobile password reset token'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    token = fields.Char(required=True, copy=False)
    expires_at = fields.Datetime(required=True)
    used = fields.Boolean(default=False)

    _token_unique = models.Constraint('unique(token)', 'The reset token must be unique.')

    @api.model
    def create_for_login(self, login):
        """ 为登录名对应的有效用户创建令牌; 用户不存在或已停用时返回空记录 """
        user = self.env['res.users'].sudo().search([('login', '=', login), ('active', '=', True)], limit=1)
        if not user:
            return self.browse()
        return self.sudo().create({
            'user_id': user.id,
            'token': secrets.token_urlsafe(32),
            'expires_at': fields.Datetime.now() + RESET_VALIDITY,
        })

    @api.model
    def get_valid(self, token):
        """ 返回未使用、未过期、且用户仍有效的令牌记录; 否则返回空记录 """
        if not token:
            return self.browse()
        record = self.sudo().search([('token', '=', token)], limit=1)
        if record and not record.used and record.expires_at > fields.Datetime.now() and record.user_id.active:
            return record
        return self.browse()

    def reset_link(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url', '')
        return f"{base_url}/mobile_web/reset_password/{self.token}"

    def deliver(self):
        """ 发送重置链接. 发送依赖 mail 模块; 未安装时返回 False, 由页面提示"暂未开放" """
        self.ensure_one()
        if 'mail.mail' not in self.env:
            return False
        self.env['mail.mail'].sudo().create({
            'subject': _("Reset your password"),
            'body_html': _("<p>Follow this link to set a new password: <a href=\"%s\">%s</a></p>",
                           self.reset_link(), self.reset_link()),
            'email_to': self.user_id.email or self.user_id.login,
            'auto_delete': True,
        })
        return True

    def set_password(self, password):
        """ 设置新密码并使令牌失效 """
        self.ensure_one()
        if len(password or '') < MIN_PASSWORD_LENGTH:
            raise UserError(_("The password must be at least %s characters long.", MIN_PASSWORD_LENGTH))
        self.user_id.sudo().write({'password': password})
        self.used = True

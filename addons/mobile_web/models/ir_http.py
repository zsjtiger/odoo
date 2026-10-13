# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from odoo.http.session import SessionExpiredException, get_session_max_inactivity, session_store


class IrHttpMobileExtend(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_error(cls, exception):
        """
        对于odoo.http.HttpDispatcher, 遇到SessionExpiredException默认重定向到/web/login
        手机端适配, 根据request的url, 手机端的请求重定向到/mobile_web/login
        """
        # TODO: 这可能不是个好方式，错误处理应当在HttpDispatcher中处理，IrHttp负责调用
        if isinstance(exception, SessionExpiredException):
            req_path: str = request.httprequest.path
            # TODO: cotext也可以判断
            if req_path.startswith('/mobile_web'):
                session = request.session
                was_connected = session.uid is not None
                response = request.redirect_query('/mobile_web/login', {'redirect': request.httprequest.full_path})
                if was_connected:
                    session_store().rotate(session, request.env)
                    response.set_cookie(
                        'session_id',
                        session.sid,
                        max_age=get_session_max_inactivity(request.env),
                        httponly=True
                    )
                return response

        return super()._handle_error(exception)

    def webclient_rendering_context(self):
        """
        手机端中的webclient_bootstrap模板的渲染不需要menu_data
        """
        return {
            'session_info': self.session_info(),
        }

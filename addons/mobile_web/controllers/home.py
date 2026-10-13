# -*- coding: utf-8 -*-
import json
import werkzeug
from werkzeug.urls import url_encode

import crossnow
import crossnow.exceptions
from crossnow import http
from crossnow.tools import ustr
from crossnow.http import request
from crossnow.service import security
from crossnow.tools.translate import _
from crossnow.exceptions import AccessError

from crossnow.addons.web.controllers.utils import ensure_db, is_user_internal
from crossnow.addons.web.controllers.home import SIGN_UP_REQUEST_PARAMS, CREDENTIAL_PARAMS, LOGIN_SUCCESSFUL_PARAMS


mobile_context = {
    'ir.ui.menu.current_device': 'mobile'
}


class Home(http.Controller):
    @http.route(['/mobile_web', '/mobile_web/<path:js_router_path>'], type='http', auth='none')
    def mobile_web_client(self, **kw):
        """
        * 未登录，重定向至登录页面
        * 已登录，渲染前端页面
        """
        ensure_db()

        request.update_context(**mobile_context)

        if not request.session.uid:
            return request.redirect_query('/mobile_web/login', query={'redirect': request.httprequest.full_path}, code=303)
        if kw.get('redirect'):
            return request.redirect(kw.get('redirect'), 303)
        if not security.check_session(request.session, request.env, request):
            raise http.SessionExpiredException("Session expired")
        if not is_user_internal(request.session.uid):
            return request.redirect('/mobile_web/login_successful', 303)

        # Side-effect, refresh the session lifetime
        request.session.touch()

        request.update_env(user=request.session.uid)
        try:
            # 这个context里主要是前端需要的session信息, 包括了user、db等
            context = request.env['ir.http'].webclient_rendering_context()
            response = request.render('mobile_web.webclient_bootstrap', qcontext=context)
            response.headers['X-Frame-Options'] = 'DENY'
            return response
        except AccessError:
            return request.redirect('/mobile_web/login?error=access')

    @http.route('/mobile_web/login', type='http', auth='none')
    def mobile_web_login(self, redirect=None, **kw):
        """
        * GET请求, 获取登录页面
        * POST请求, 处理登录逻辑
        """
        ensure_db()

        # 处理http request的参数, 逻辑与web一致
        request.params['login_success'] = False
        if request.httprequest.method == 'GET' and redirect and request.session.uid:
            return request.redirect(redirect)
        if request.env.uid is None:
            if request.session.uid is None:
                request.env["ir.http"]._auth_method_public()
            else:
                request.update_env(user=request.session.uid)

        values = {k: v for k, v in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        try:
            values['databases'] = http.db_list()
        except crossnow.exceptions.AccessDenied:
            values['databases'] = None

        if request.httprequest.method == 'POST':
            """ 登录处理逻辑 """
            try:
                credential = {key: value for key, value in request.params.items() if key in CREDENTIAL_PARAMS}
                credential.setdefault('type', 'password')
                auth_info: dict = request.session.authenticate(request.session.db, credential)
            except crossnow.exceptions.AccessDenied as e:
                # 登录失败, 处理values(渲染web.login的qweb context), 下面的逻辑重新渲染login页面
                if e.args == crossnow.exceptions.AccessDenied().args:
                    values['error'] = _("Wrong login/password")
                else:
                    values['error'] = e.args[0]
            else:
                uid = auth_info['uid']
                request.params['login_success'] = True
                return request.redirect(self._login_redirect(uid, redirect=redirect))
        else:
            if 'error' in request.params and request.params.get('error') == 'access':
                values['error'] = _('Only employees can access this database. Please contact the administrator.')

        # 渲染登录页面
        if 'login' not in values and request.session.get('auth_login'):
            values['login'] = request.session.get('auth_login')
        if not crossnow.tools.config['list_db']:
            values['disable_database_manager'] = True

        response = request.render('mobile_web.login', values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @http.route('/mobile_web/retrieve_password', type='http', auth='none')
    def mobile_web_retrieve_password(self, redirect=None, **kw):
        values = {}
        response = request.render('mobile_web.login_retrieve_password', values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"

        return response

    @http.route('/mobile_web/login_successful', type='http', auth='user', website=True, sitemap=False)
    def login_successful_external_user(self, **kwargs):
        """ 非内部用户登录后显示的界面 """
        valid_values = {k: v for k, v in kwargs.items() if k in LOGIN_SUCCESSFUL_PARAMS}
        return request.render('mobile_web.login_successful', valid_values)

    @http.route('/mobile_web/webclient/load_menus/<string:unique>', type='http', auth='user', methods=['GET'], readonly=True)
    def mobile_web_load_menus(self, unique, lang=None):
        """
        加载手机端的menu data
        此请求为http type的GET请求, 无法从前端构建的请求中附加context, 因此创建一个手机端的load_menus Controller Function.
        """
        if lang:
            request.update_context(lang=lang)

        request.update_context(**mobile_context)

        menus_data = request.env["ir.ui.menu"].load_web_menus(request.session.debug)
        request_body = json.dumps(menus_data, default=ustr)
        response = request.make_response(request_body, [
            ('Content-Type', 'application/json'),
        ])
        return response
    
    @http.route('/mobile_web/page_actions/load', type='json', auth='user', readonly=True)
    def mobile_page_load_actions(self, mobile_page_id, context=None):
        if context:
            request.update_context(**context)
        return request.env['mobile_web.mobile.page.actions'].get_page_actions(mobile_page_id)

    def _login_redirect(self, uid, redirect=None):
        """
        逻辑与addons.web.controller.main._get_login_redirect_url是一致的
        这里默认要redirect到mobile_web
        """
        suid = request.session.uid
        if suid:  # fully logged
            return redirect or ('/mobile_web' if is_user_internal(suid) else '/mobile_web/login_successful')

        # partial session (MFA)
        url = request.env(user=uid)['res.users'].browse(uid)._mfa_url()
        if not redirect:
            return url

        parsed = werkzeug.urls.url_parse(url)
        qs = parsed.decode_query()
        qs['redirect'] = redirect
        return parsed.replace(query=werkzeug.urls.url_encode(qs)).to_url()

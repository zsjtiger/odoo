# -*- coding: utf-8 -*-
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import odoo.exceptions
from odoo import _
from odoo.exceptions import AccessError
from odoo.http import request, route
from odoo.http.router import db_list
from odoo.http.session import authenticate, check, touch
from odoo.tools import config

from odoo.addons.web.controllers.home import CREDENTIAL_PARAMS, LOGIN_SUCCESSFUL_PARAMS, SIGN_UP_REQUEST_PARAMS
from odoo.addons.web.controllers.home import Home as WebHome
from odoo.addons.web.controllers.utils import ensure_db, is_user_internal


mobile_context = {
    'ir.ui.menu.current_device': 'mobile'
}


# 继承 web 的 Home: 登录、会话、数据库等 web 的路由保持不变.
# 注意: Odoo 中同名方法会覆盖父类(web)的路由, 因此移动端的方法都使用 mobile 相关的名字.
class Home(WebHome):
    @route(['/mobile_web', '/mobile_web/<path:js_router_path>'], type='http', auth='none')
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
        check(request.session, request)  # raises SessionExpiredException when the session is expired
        if not is_user_internal(request.session.uid):
            return request.redirect('/mobile_web/login_successful', 303)

        # Side-effect, refresh the session lifetime
        touch(request.session)

        request.update_env(user=request.session.uid)
        try:
            # 这个context里主要是前端需要的session信息, 包括了user、db等
            context = request.env['ir.http'].webclient_rendering_context()
            response = request.render('mobile_web.webclient_bootstrap', qcontext=context)
            response.headers['X-Frame-Options'] = 'DENY'
            return response
        except AccessError:
            return request.redirect('/mobile_web/login?error=access')

    @route('/mobile_web/login', type='http', auth='none')
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
                request.env["ir.http"]._auth_method_public({})
            else:
                request.update_env(user=request.session.uid)

        values = {k: v for k, v in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        try:
            values['databases'] = db_list()
        except odoo.exceptions.AccessDenied:
            values['databases'] = None

        if request.httprequest.method == 'POST':
            """ 登录处理逻辑 """
            try:
                credential = {key: value for key, value in request.params.items() if key in CREDENTIAL_PARAMS and value}
                credential.setdefault('type', 'password')
                # 与web登录保持一致: 需要验证码时先校验验证码
                if request.env['res.users']._should_captcha_login(credential):
                    request.env['ir.http']._verify_request_recaptcha_token('login')
                auth_info: dict = authenticate(request.session, request.env, credential)
            except odoo.exceptions.AccessDenied as e:
                # 登录失败, 处理values(渲染web.login的qweb context), 下面的逻辑重新渲染login页面
                if e.args == odoo.exceptions.AccessDenied().args:
                    values['error'] = _("Wrong login/password")
                else:
                    values['error'] = e.args[0]
            else:
                uid = auth_info['uid']
                request.params['login_success'] = True
                return request.redirect(self._mobile_login_redirect(uid, redirect=redirect))
        else:
            if 'error' in request.params and request.params.get('error') == 'access':
                values['error'] = _('Only employees can access this database. Please contact the administrator.')

        # 渲染登录页面
        if 'login' not in values and request.session.get('auth_login'):
            values['login'] = request.session.get('auth_login')
        if not config['list_db']:
            values['disable_database_manager'] = True

        response = request.render('mobile_web.login', values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @route('/mobile_web/retrieve_password', type='http', auth='none', methods=['GET', 'POST'], readonly=False)
    def mobile_web_retrieve_password(self, login=None, **kw):
        """
        找回密码: 提交登录名后发送重置链接.
        无论账号是否存在、是否能发送, 页面给出的结果相同, 避免泄露账号信息.
        """
        values = {'message': None}
        if request.httprequest.method == 'POST':
            reset = request.env['mobile_web.password.reset'].sudo().create_for_login(login) if login else None
            if reset:
                reset.deliver()
            values['message'] = _("If the account exists, a reset link has been sent to its email address.")
        response = request.render('mobile_web.login_retrieve_password', values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @route('/mobile_web/reset_password/<string:token>', type='http', auth='none', methods=['GET', 'POST'], readonly=False)
    def mobile_web_reset_password(self, token, password=None, confirm_password=None, **kw):
        """ 设置新密码: 令牌有效时显示表单, 提交后令牌失效 """
        reset = request.env['mobile_web.password.reset'].get_valid(token)
        values = {'valid': bool(reset), 'token': token, 'error': None, 'done': False}
        if reset and request.httprequest.method == 'POST':
            if password != confirm_password:
                values['error'] = _("The passwords do not match.")
            else:
                try:
                    reset.set_password(password)
                    values['done'] = True
                except odoo.exceptions.UserError as e:
                    values['error'] = e.args[0]
        response = request.render('mobile_web.login_new_password', values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @route('/mobile_web/login_successful', type='http', auth='user')
    def mobile_login_successful(self, **kwargs):
        """ 非内部用户登录后显示的界面 """
        valid_values = {k: v for k, v in kwargs.items() if k in LOGIN_SUCCESSFUL_PARAMS}
        return request.render('mobile_web.login_successful', valid_values)

    @route('/mobile_web/webclient/load_menus/<string:unique>', type='http', auth='user', methods=['GET'], readonly=True)
    def mobile_web_load_menus(self, unique, lang=None):
        """
        加载手机端的menu data
        此请求为http type的GET请求, 无法从前端构建的请求中附加context, 因此创建一个手机端的load_menus Controller Function.
        """
        if lang:
            request.update_context(lang=lang)

        request.update_context(**mobile_context)

        menus_data = request.env["ir.ui.menu"].load_web_menus(request.session.debug)
        request_body = json.dumps(menus_data, default=str)
        response = request.make_response(request_body, [
            ('Content-Type', 'application/json'),
        ])
        return response
    
    @route('/mobile_web/page_actions/load', type='json', auth='user', readonly=True)
    def mobile_page_load_actions(self, mobile_page_id, context=None):
        if context:
            request.update_context(**context)
        return request.env['mobile_web.mobile.page.actions'].get_page_actions(mobile_page_id)

    def _mobile_login_redirect(self, uid, redirect=None):
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

        parts = urlsplit(url)
        qs = dict(parse_qsl(parts.query))
        qs['redirect'] = redirect
        return urlunsplit(parts._replace(query=urlencode(qs)))

    @route('/mobile_web/search_domain', type='json', auth='user', readonly=True)
    def mobile_search_domain(self, model, text=''):
        """
        手机端的简单搜索: 把输入的文本转换为模型 `_rec_name` 字段上的 ilike 条件.
        没有 `_rec_name` 的模型不做搜索(返回空条件).
        """
        text = (text or '').strip()
        if not text or model not in request.env:
            return []
        rec_name = request.env[model]._rec_name
        if not rec_name or rec_name not in request.env[model]._fields:
            return []
        return [(rec_name, 'ilike', text)]

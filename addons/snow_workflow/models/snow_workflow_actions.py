import json
import logging
from odoo import models, api, _
from odoo.exceptions import UserError
from ..workflow.button import ButtonCompute
from ..workflow.snow_workflow import SnowWorkflow

Logger = logging.getLogger(__name__)


class WorkflowAction(models.AbstractModel):
    _name = 'snow.workflow.action'

    def _page_refresh_action(self, model_name, record_id, view_id, context):
        """
        返回PC端重新加载页面的action
        :param model_name:
        :param record_id:
        :return:
        """
        record = self.env[model_name].browse(record_id)
        if record.exists() and record.display_name:
            title = record.display_name
        else:
            title = 'Submit Success'
        return {
            'name': title,
            "tag": "submit_success",
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': model_name,
            'view_id': False,
            'views': [
                (view_id, 'form'),
            ],
            'target': 'main',
            'context': context,
            'type': 'ir.actions.act_window',
            'domain': [],
            'res_id': record_id
        }

    def _popup_action(self):
        """
        返回PC端弹窗的action
        :return:
        """
        titles = {
            'pass': _('Pass Operation'),
            'reject': _('Reject Operation'),
            'withdraw': _('Withdraw Operation'),
        }
        button_name = self.env.context.get('button_name')
        return {
            'name': titles.get(button_name, _('information')),
            'type': 'ir.actions.act_window',
            'res_model': 'snow.workflow.instance',
            'view_mode': 'form',
            'tag': 'other_form',
            'target': 'new',
            'context': self.env.context,
            'views': [
                (self.env.ref('snow_workflow.snow_workflow_warning_form').sudo().id, 'form'),
            ],
        }

    def risk_warning_action(self):
        """
        PC端 和 手机端 公用action
        产品中，默认只做风险提示，snow_common中覆盖更全面逻辑（安装snow_common才有必要内容）
        :return:
        """
        # 回调业务模块实施定义逻辑
        self.business_model_call_back(self.env.context.get('model_name'),
                                      self.env.context.get('record_id'),
                                      'before_risk_warning')
        return {
            'name': _('risk information'),
            'type': 'ir.actions.act_window',
            'res_model': 'snow.workflow.instance',
            'view_mode': 'form',
            "tag": "submit_alert",
            'target': 'new',
            'context': self.env.context,
            'views': [
                (self.env.ref('snow_workflow.snow_workflow_risk_warning_form').sudo().id, 'form'),
            ],
        }

    def business_model_call_back(self, model_name, record_id, time_node):
        model = self.env['ir.model']._get(model_name)
        if not model:
            model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
        model_id = model.id if model else None
        search_condition = [('object_id', '=', model_id), ('wf_state', '=', time_node)]
        business_record = self.env[model_name].browse([record_id])
        order_action = self.env['snow.workflow.state.action'].sudo().search(search_condition,
                                                                            order='order')
        for action in order_action:
            if hasattr(business_record, action.action):
                method = getattr(business_record, action.action)
                if callable(method):
                    method()

    def add_attendee_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('select user'),
            'res_model': 'snow.workflow.attendee.selection',
            'view_mode': 'form',
            'target': 'new',
            'views': [(self.env.ref('snow_workflow.workflow_add_attendee').sudo().id, 'form'), ],
            'context': self.env.context,
        }

    @api.model
    def get_submit_and_save_properties(self, model_name, record_id):
        # 有可能是撤销后，再次编辑点击保存并提交，需要确认是否存在instance
        instance = self.env['snow.workflow.instance'].sudo().search([
            ('object', '=', model_name),
            ('record_id', '=', record_id)
        ])
        if not instance:
            definition = self.env['snow.workflow.definition'].fetch_definition(model_name,
                                                                               record_id)
        else:
            definition = instance.wf_definition
        value = ''
        if definition:
            value = {
                # 本组参数目的支持风险提示组件
                'temporary_verify_info_title': _('risk information'),
                'temporary_verify_title': _('submit information'),
                'temporary_verify_info': definition.informed_consent,
                'confirm': {
                    'method': 'do_workflow_action',
                    'model': 'snow.workflow.action',
                },
                # trigger_function 和 kwargs 为直接提交和弹窗提交准备
                'trigger_function': 'do_submit',
                'kwargs': {'instance': instance.id if instance else None,
                           'model': model_name,
                           'record': record_id},
                'model_name': model_name,
                'record_id': record_id
            }
        return value

    @api.model
    def submit_after_save(self, model_name, record_id):
        value = self.get_submit_and_save_properties(model_name, record_id)
        if value:
            return self.approval_action(value)
        return ''

    @api.model
    def approval_action(self, value):
        """
        与前端按钮事件绑定，做提交审批/审批通过/审批拒绝等操作

        :param value: 操作信息
        :return: action pc端页面执行动作
        """
        is_dialog = value.get('is_dialog')
        add_attendee = value.get('add_attendee')
        context = self.env.context.copy()
        context.update(value)
        if context.get('trigger_function') == 'do_submit':
            context.update(
                {'verify_confirm': {'model': 'snow.workflow.alert', 'method':
                    'write_and_verify_data'}})
        # 上下文只作用于本次调用, 不修改共享的 env
        self = self.with_context(context)
        if context.get('trigger_function') == 'do_submit':
            action = self.risk_warning_action()
        elif is_dialog:
            # 需要弹出窗口的，窗口的确认按钮绑定到本类方法中做进一步处理
            action = self._popup_action()
        elif add_attendee:
            action = self.add_attendee_action()
        else:
            action = self.do_workflow_action()
        return action

    @api.model
    def _allowed_action_kwargs(self, model_name, record_id, trigger_function, client_kwargs):
        """
        校验当前用户能否执行该操作: 只有按钮计算结果中存在同名操作时才允许, 返回服务端按钮上的参数

        :param client_kwargs: 前端回传的参数, 只用于匹配实例和任务
        :return: dict 服务端计算的操作参数
        """
        for button in ButtonCompute(self.env).get_available_buttons(model_name, record_id):
            server_kwargs = button.get('kwargs') or {}
            if button.get('trigger_function') != trigger_function:
                continue
            if all(server_kwargs.get(key) == client_kwargs.get(key)
                   for key in ('instance', 'task_name') if key in client_kwargs):
                return server_kwargs
        raise UserError(_("This action is not available to you now, the task may have been handled already."))

    @api.model
    def do_workflow_action(self):
        """
        工作流前端弹出提示窗口后，点击确认统一处理方法
        参数通过context传递
        :return: action - 页面刷新动作
        """
        context = self.env.context
        # keep_context 保存 execution_id 防止用户做拒绝操作后看到所有节点
        keep_context = {}
        if 'context' in self.env.context and 'execution_id' in self.env.context['context']:
            keep_context = {'execution_id': self.env.context['context'].get('execution_id')}
        # 操作与参数以服务端按当前用户算出的按钮为准, 前端回传的参数只用来匹配
        kwargs = self._allowed_action_kwargs(context.get('model_name'), context.get('record_id'),
                                             context.get('trigger_function'),
                                             context.get('kwargs') or {})
        wf_instance_record = self.env['snow.workflow.instance'].sudo().search([
            ('object', '=', context.get('model_name')),
            ('record_id', '=', context.get('record_id'))
        ])
        snow_workflow = SnowWorkflow(self.env, wf_instance_record)
        method = context.get('trigger_function')
        # 若有comment则入库
        if ('submit_info' in self.env.context and self.env.context['submit_info']
                and 'instance' in kwargs and kwargs['instance']):
            # 通过 instance 查找当前正在进行的任务
            self.env['snow.workflow.execution.task.data'].create_data_for_task(
                kwargs['instance'], context.get('trigger_function'),
                self.env.context['submit_info'], self.env.user)

        # 执行审批动作
        snow_workflow_method = getattr(snow_workflow, method, None)
        if not callable(snow_workflow_method):
            raise UserError(_("Unknown workflow action: %s", method))
        snow_workflow_method(**kwargs)
        # 获取定义时的target_view
        definition = self.env['snow.workflow.definition'].fetch_definition(
            context.get('model_name'), context.get('record_id'))
        target_view_id = definition['target_view'].id if definition else False
        # 刷新页面
        action = self._page_refresh_action(context.get('model_name'), context.get('record_id'),
                                           target_view_id,
                                           keep_context)
        return action

    @api.model
    def get_status(self, model_name, record_id):
        """
        获得记录状态，决定按钮渲染

        :param model_name: 对应业务模块
        :param record_id: 记录id
        :return: 按钮的显示状态
        """
        button_list = ButtonCompute(self.env).get_available_buttons(model_name, record_id)
        for button in button_list:
            if 'context' in button:
                button['context'].update(self.env.context)
            else:
                button['context'] = self.env.context
        return button_list

    @api.model
    def get_save_and_submit_button(self, model_name, record_id):
        """
        获得保存并提交按钮
        :param model_name: 业务模型
        :param record_id: 记录id
        :return: 保存并提交按钮或空
        """
        button = ButtonCompute(self.env).get_save_and_submit_button(model_name, record_id)
        return button

    @api.model
    def get_process_json(self, model_name, record_id):
        """
        获得审批进度json

        :param model_name: 对应业务模块
        :param record_id: 记录id
        :return: 进度json
        """
        execution_id = self.env.context.get('execution_id')
        if execution_id:
            execution = self.env['snow.workflow.execution'].with_context(_type='').sudo().search(
                [('id', '=', execution_id)])
            json_data = json.dumps([json.loads(execution.vision_data)]) \
                if execution.vision_data else []
            return json_data
        instance = self.env['snow.workflow.instance'].with_context(_type='').sudo().search([
            ('object', '=', model_name),
            ('record_id', '=', record_id)
        ])
        if instance:
            executions = instance.wf_executions.sorted(key=lambda r: r.create_date,
                                                       reverse=True)
            child_visions = [json.loads(record.vision_data)
                             for record in executions if record.vision_data]
            json_data = json.dumps(child_visions)
            return json_data
        return []

from odoo import _
from .attendee import TaskAttendee
from . import GROUP_APPROVE_EXECUTION_TASKS
from .exceptions import SnowWorkflowValidationError


SUSPEND_BUTTON = 'suspend'
UNSUSPEND_BUTTON = 'unsuspend'
SUBMIT_BUTTON = 'submit'
PASS_BUTTON = 'pass'
REJECT_BUTTON = 'reject'
WITHDRAW_BUTTON = 'withdraw'
ADD_ATTENDEE = 'add_attendee'


class ButtonCompute:
    """
    控制workflow的按钮显示
    """

    def __init__(self, env, workflow_instance=None):
        self.env = env
        self.workflow_definition = None
        self.workflow_instance = workflow_instance
        self.task_name = None
        self.model = None
        self.record = None

        self.reject_message = 'Please enter the reason for refusal'

        # 特殊标志
        self.group_flag = False

    @property
    def suspend_button_info(self):
        return {
            'button_name': 'suspend',
            'is_dialog': False,
            'trigger_function': 'do_suspend',
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    @property
    def unsuspend_button_info(self):
        return {
            'button_name': 'unsuspend',
            'is_dialog': False,
            'trigger_function': 'do_unsuspend',
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    @property
    def save_and_submit_button(self):
        return {
            'button_name': 'save and submit',
            'is_dialog': False,
            'trigger_function': 'do_submit',
            'kwargs': {'instance': None,
                       'model': self.model,
                       'record': self.record}
        }

    @property
    def submit_approve_button_info(self):
        btn_name = 'submit for approval'
        trigger_function = 'do_submit'
        # 第一次提交时，实例化未传入instance
        definition = self.workflow_instance.wf_definition if self.workflow_instance else self.workflow_definition

        action = {
            'button_name': btn_name,
            # 本组参数目的支持风险提示组件
            'temporary_verify_info_title': _('risk information'),
            'temporary_verify_title': _('submit information'),
            'temporary_verify_info': definition.informed_consent,
            'confirm': {
                'method': 'do_workflow_action',
                'model': 'snow.workflow.action',
            },
            # trigger_function 和 kwargs 为直接提交和弹窗提交准备
            'trigger_function': trigger_function,
            'kwargs': {'instance': self.workflow_instance.id if self.workflow_instance else None,
                       'model': self.model,
                       'record': self.record}
        }
        return action

    def approve_execution_do_pass_button_info(self, options=None):
        trigger_function = 'do_multi_pass' if self.group_flag else 'do_single_pass'
        is_submit_text = options.get('is_approval_message_required', False)

        return {
            'button_name': 'pass',
            'show_check_box': False,
            'is_dialog': self.workflow_instance.wf_definition.show_alert_before_approval,
            'is_submit_text': is_submit_text,
            'temporary_verify_info': self.workflow_instance.wf_definition.approval_alert_message,
            'confirm': {
                'method': 'do_workflow_action',
                'model': 'snow.workflow.action',
            },
            'trigger_function': trigger_function,
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    def approve_execution_do_reject_button_info(self, options=None):
        trigger_function = 'do_multi_reject' if self.group_flag else 'do_single_reject'
        is_submit_text = options.get('is_reject_message_required', False)

        return {
            'button_name': 'reject',
            'show_check_box': False,
            'is_dialog': self.workflow_instance.wf_definition.show_alert_before_reject,
            'is_submit_text': is_submit_text,
            'temporary_verify_info': self.workflow_instance.wf_definition.reject_alert_message,
            'confirm': {
                'method': 'do_workflow_action',
                'model': 'snow.workflow.action',
            },
            'trigger_function': trigger_function,
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    @property
    def do_withdraw_button_info(self):
        return {
            'button_name': 'withdraw',
            'is_dialog': False,
            'trigger_function': 'do_withdraw',
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    @property
    def add_attendee_button_info(self):
        return {
            'button_name': 'add attendee',
            'add_attendee': True,
            'trigger_function': 'add_attendee',
            'kwargs': {'instance': self.workflow_instance.id, 'task_name': self.task_name}
        }

    def _button_name_mapping_convert(self, button_names: set, options=None) -> list:
        """
        按固定顺序，将按钮名转成按钮列表
        """
        ordered_button = [UNSUSPEND_BUTTON, SUSPEND_BUTTON, WITHDRAW_BUTTON, REJECT_BUTTON,
                          PASS_BUTTON, SUBMIT_BUTTON, ADD_ATTENDEE]
        button_list = []
        for button in ordered_button:
            if button not in button_names:
                continue
            if button == UNSUSPEND_BUTTON:
                button_list.append(self.unsuspend_button_info)
            elif button == SUSPEND_BUTTON:
                button_list.append(self.suspend_button_info)
            elif button == WITHDRAW_BUTTON:
                button_list.append(self.do_withdraw_button_info)
            elif button == REJECT_BUTTON:
                button_list.append(self.approve_execution_do_reject_button_info(options))
            elif button == PASS_BUTTON:
                button_list.append(self.approve_execution_do_pass_button_info(options))
            elif button == SUBMIT_BUTTON:
                button_list.append(self.submit_approve_button_info)
            elif button == ADD_ATTENDEE:
                button_list.append(self.add_attendee_button_info)
        return button_list

    def get_save_and_submit_button(self, model_name, record_id):
        """
        获取保存并提交按钮
        :param model_name:
        :param record_id:
        :return:
        """
        self.model = model_name
        self.record = record_id
        if not record_id:
            return self.save_and_submit_button

        record = self.env[model_name].sudo().search([('id', '=', record_id)])
        create_uid_id = record.create_uid.id if record else None
        if create_uid_id == self.env.uid:
            instance = self.env['snow.workflow.instance'].sudo().search([
                ('object', '=', model_name),
                ('record_id', '=', record_id)
            ])
            if not instance or instance.status not in ['approve_pending', 'suspending', 'pass']:
                return self.save_and_submit_button
        return ''

    def get_available_buttons(self, model_name, record_id, options=None):
        """
        整个类的入口，计算要显示哪些按钮

        :return: 按钮列表
        """
        button_names = set()
        if not model_name or not record_id:
            return list()

        # 获取对应的instance 和 业务数据
        instance = self.env['snow.workflow.instance'].sudo().search([
            ('object', '=', model_name),
            ('record_id', '=', record_id)
        ])

        res_record = self.env[model_name].sudo().browse(record_id)
        self.model = model_name
        self.record = record_id
        # 如果还没有生成instance，业务数据创建者可以提交
        if not instance:
            if self.env.uid == res_record.create_uid.id:
                self.workflow_definition = self.env['snow.workflow.definition'].fetch_definition(model_name, record_id)
                button_names.add(SUBMIT_BUTTON)
            return self._button_name_mapping_convert(button_names)

        self.workflow_instance = instance
        # 如果instance有，但是没有未完成的execution，业务数据创建者可提交
        if all(record.is_complete for record in
               self.workflow_instance.wf_executions) and self.workflow_instance.status != 'pass':
            if self.env.uid == res_record.create_uid.id:
                button_names.add(SUBMIT_BUTTON)
            return self._button_name_mapping_convert(button_names)

        # 工作流已经完成了，什么按钮都不显示
        if self.workflow_instance.is_complete:
            return list()

        # 根据当前WorkflowInstance，获取当前正在进行的任务，正在进行的任务只有一个
        task_record = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', self.workflow_instance.id), ('in_progress', '=', True)]
        )
        self.task_name = task_record.task_xml_id

        if not task_record:
            return list()

        if len(task_record) > 1:
            raise SnowWorkflowValidationError("There are multipal ready tasks in the current instance")

        # 挂起/恢复
        if self.workflow_instance.status == 'suspending':
            button_names = self._add_unsuspend_button_names(button_names)
            return self._button_name_mapping_convert(button_names)

        button_names = self._add_external_suspend_button_names(button_names)

        # 审批流相关按钮
        button_names = self._add_approval_button_names(button_names, task_record)
        return self._button_name_mapping_convert(button_names, options)

    def _add_approval_button_names(self, button_names: set, task_record):
        """
        审批相关按钮
        """

        approve_task_type = task_record.task_xml_name

        # 给提交人添加撤销按钮
        if self.env.uid == task_record.wf_instance.initiator.id:
            button_names.add(WITHDRAW_BUTTON)

        if self.env.uid not in [record.user.id for record in task_record.task_attendee]:
            return button_names

        # 审批操作任务
        if approve_task_type == "approve_execution":
            self.add_approval_buttons(task_record, button_names)

        # 会签、或签操作任务
        elif approve_task_type in GROUP_APPROVE_EXECUTION_TASKS:
            self.group_flag = True
            # 会签审批&有操作此会签审批任务的权限
            if ((approve_task_type == 'group_approve_execution_and'
                    and TaskAttendee(self.env).is_executable_for_multi_approve_and(task_record))
                    or approve_task_type == 'group_approve_execution_or'):
                # 审批通过、拒绝按钮
                self.add_approval_buttons(task_record, button_names)

        # 其他无法识别的任务
        else:
            raise SnowWorkflowValidationError(f"Can not recognize task:{approve_task_type}")

        return button_names

    def add_approval_buttons(self, task_record, button_names):
        """
        添加审批相关按钮。
        """
        button_names.add(PASS_BUTTON)
        button_names.add(REJECT_BUTTON)

        wf_definition = task_record.wf_instance.wf_definition

        if wf_definition.is_internal_suspend:
            button_names.add(SUSPEND_BUTTON)

        if wf_definition.can_add_attendee:
            button_names.add(ADD_ATTENDEE)

    def _add_external_suspend_button_names(self, button_names: set):
        """
        挂起按钮计算
        """
        # 计算工作流挂起按钮，wf_definition上配置了“可挂起”, 审批流在approve_pending状态中, 并且当前登录用户有权执行挂起
        if (self.workflow_instance.wf_definition.is_external_suspend and
                self.workflow_instance.status == 'approve_pending'):
            if self._is_external_manager():

                # 添加挂起、拒绝按钮
                button_names.add(SUSPEND_BUTTON)
                button_names.add(REJECT_BUTTON)

        return button_names

    def _add_unsuspend_button_names(self, button_names):
        """
        挂起恢复按钮计算
        """
        if self._unsuspend_button_rule():
            button_names.add(UNSUSPEND_BUTTON)
        return button_names

    def _is_external_manager(self) -> bool:
        """
        判断是否是外部管理人员
        """
        managers = self.env['snow.workflow.external.managers'].search([
            ('definition_id', '=', self.workflow_instance.wf_definition.id)
        ])

        return self.env.uid in [manager.user_id.id for manager in managers]

    def _unsuspend_button_rule(self) -> bool:
        """
        解除挂起 按钮显示规则
        """
        # base规则, 谁挂起谁解除
        return self.env.user.id == self.workflow_instance.suspend_info.suspend_user.id

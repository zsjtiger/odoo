# -*- coding: utf-8 -*-
import json
import logging
import datetime
import functools

from crossnow.exceptions import UserError
from .attendee import TaskAttendee
from .status import WorkflowStatus
from .vision import SnowWorkflowVision
from .engines import BpmnWorkflowEngine
from .util import SnowWorkflowRecordUtil
from .exceptions import SnowWorkflowValidationError, SnowWorkflowRuntimeError
from . import APPROVE_EXECUTION_TASKS, GROUP_APPROVE_EXECUTION_TASKS

logger = logging.getLogger(__name__)


def _snow_workflow_user_action(method):
    """
    针对`SnowWorkflow`中的用户操作, 进行统一操作:
    1. 检查传入的参数
    2. 检查当前的`snow.workflow.instance`的`is_complete`标记
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if 'task_name' not in kwargs:
            logger.warning(self.warning_info)
            return

        if self.workflow_instance.is_complete:
            return None

        return method(self, *args, **kwargs)

    return wrapper


class SnowWorkflow:
    """
    SnowWorkflow的标准接口, 所有用户的操作(do_submit, do_pass, do_reject...)都调用这里的方法
    """
    proxy_cls = None

    def __new__(cls, *args, **kwargs):
        return cls.proxy_cls(*args, **kwargs)  # pylint: disable=E1102


class SnowWorkflowMeta(type):
    def __new__(meta, name, bases, attrs):
        cls = super().__new__(meta, name, bases, attrs)
        # 发生继承时，自动更新SnowWorkflow的proxy，确保访问的是最新的类
        SnowWorkflow.proxy_cls = cls
        return cls


class SnowBaseWorkflow(metaclass=SnowWorkflowMeta):
    def __init__(self, env, workflow_instance):
        """
        :param env: crossnow.api.Environment
        :param workflow_instance: `snow.workflow.instance`的记录
        """
        self.env = env
        self.workflow_instance = workflow_instance
        # 第一次提交审批时，没有instance
        if self.workflow_instance.wf_executions.filtered(lambda r: not r.is_complete):
            self.bpmn_workflow_engine = BpmnWorkflowEngine(
                json_str=self.workflow_instance.wf_executions.filtered(lambda r: not r.is_complete)[
                    0].wf_json)
            self.main_workflow = self.bpmn_workflow_engine.load_workflow_from_json_str()
            self.record_util = SnowWorkflowRecordUtil(env, self.bpmn_workflow_engine)
        self.warning_info = 'No task id is specified for the approval action'
        self.task_mapping = {}  # 引擎推进过程中，子流程中task_id会发生变化，需要记录并更新

    def get_task_from_name(self, name):
        tasks = [t for t in self.main_workflow.get_tasks() if
                 t.get_name() == name and t.get_state_name() == 'READY']
        if len(tasks) > 1:
            logger.warning('Find multiple tasks with the same name whose status is ready')
        return tasks[0]

    def create_instance_init_data(self, model, record, instance=None):
        """
        创建初始化数据： instance数据，execution数据，所有task数据
        :param model: 对应的业务模块
        :param record: 业务数据id
        :param instance: 第一次提交时，无实例
        :return:
        """
        """
            从definition中得到审批流，推进到用户任务后保存到execution
        """
        workflow_definition = self.env['snow.workflow.definition']
        wf_def = workflow_definition.fetch_definition(model, record)
        if not wf_def:
            raise SnowWorkflowValidationError("Can not find target Workflow Definition")
        bpmn_workflow_engine = BpmnWorkflowEngine(xml_str=wf_def.content)
        workflow = bpmn_workflow_engine.get_workflow_obj_from_xml_parser()
        self.main_workflow = workflow
        # 初始化时，给脚本带入环境参数
        for task in workflow.get_tasks():
            task.set_data(model=model)
            task.set_data(record=record)
            if task.task_spec.spec_type == 'Script Task':
                task.set_data(script_env=self.env)
        workflow.do_engine_steps()
        workflow.refresh_waiting_tasks()
        events = workflow.get_waiting_tasks()
        # 如果自审批，没有正在等待的任务
        if len(events) > 0:
            # 只有一个 waiting task
            sub_workflow = workflow.get_subprocess(events[0])
            sub_workflow.do_engine_steps()
        # 推进后的流保存为json，存入execution
        wf_json = bpmn_workflow_engine.save_workflow_obj_to_json_str(workflow)
        # 将初始化未定义的参数补齐，为自动处理做准备
        self.bpmn_workflow_engine = BpmnWorkflowEngine(json_str=wf_json)
        self.record_util = SnowWorkflowRecordUtil(self.env, self.bpmn_workflow_engine)

        """
            准备task，execution，instance数据，存数据看
        """
        task_data = {}  # 为后续maybe task 准备数据
        ready_task_data = self.main_workflow.get_ready_user_tasks()
        if len(ready_task_data) > 0:
            task_data = ready_task_data[0].data
        create_tasks = [t for t in self.main_workflow.get_tasks() if
                        t.task_spec.description in APPROVE_EXECUTION_TASKS and t.state != 64]
        vision_data = []
        task_records = []
        first = True
        for create_task in create_tasks:
            if create_task.state == 1:  # maybe
                create_task.set_data(**task_data)
            # 根据task对象生成task_record的static数据
            record_util = SnowWorkflowRecordUtil(self.env, bpmn_workflow_engine)
            task_record_data = record_util.create_task_record_static_data(create_task)
            # 按顺序，第一个任务为激活状态
            if first:
                task_record_data.update({'in_progress': True})
                first = False

            task_attendee_data = TaskAttendee(self.env).lane_to_attendee_data(
                create_task.task_spec.lane,
                self.env.user,
                create_task.data
            )
            vision_members = task_attendee_data.copy()

            task_attendee = self.build_task_attendee_data(task_attendee_data)

            # 添加task_record的relation-o2m和m2o数据
            task_record_data.update({
                'task_attendee': task_attendee
            })
            if vision_members:
                vision_data.append(
                    {'task_type': create_task.get_description(),
                     'task_name': create_task.get_name(), 'members': vision_members})
            task_records.append((0, 0, task_record_data))

        """
        准备execution数据，带入task数据，创建vision_data
        """
        submit_comment = ''
        if 'submit_info' in self.env.context and self.env.context['submit_info']:
            # 处理一下提交时的确认信息
            submit_comment = self.env.context['submit_info']

        create_execution = {
            'wf_execution_tasks': task_records,
            'wf_json': wf_json,
            'is_complete': False,
            'vision_data': json.dumps(
                SnowWorkflowVision(self.env).init_vision_data(self.env.user,  # pylint: disable=E1101
                                                              submit_comment,
                                                              vision_data, model=model,
                                                              record=record),
                ensure_ascii=False
            )
        }
        # 无instance是第一次提交，同时创建instance；有instance是被拒后提交，不用创建instance
        if instance:
            create_execution.update({'wf_instance': instance})
            self.env['snow.workflow.execution'].sudo().create(create_execution)
            self.workflow_instance = self.env['snow.workflow.instance'].browse(instance)
        else:
            # 判断是否已经存在instance，如果存在，已经初始化过，不该进入，可能双击提交多次，跳出
            if self.env['snow.workflow.instance'].sudo().search(
                    [('object', '=', model), ('record_id', '=', record)]):
                return
            execution_data = [(0, 0, create_execution)]
            """
            创建instance数据，带入execution数据
            """
            self.workflow_instance = self.env['snow.workflow.instance'].sudo().create({
                'wf_definition': wf_def.id,
                'start_time': datetime.datetime.now(),
                'end_time': None,
                'wf_executions': execution_data,
                'record_id': record,
                'initiator': self.env.uid,
                'is_complete': False,
            })
        # 分别处理自审批 和 普通提交审批
        if len(events) == 0:
            # 自审批没有历史任务，为了在已处理列表中留存数据，创建一条历史数据
            task_history = self.env['snow.workflow.execution.task.history'].create({
                'task_xml_name': 'self_submit_approve',
                'wf_execution': self.workflow_instance.wf_executions[-1].id,
                'wf_instance': self.workflow_instance.id
            })
            self.env['snow.workflow.execution.task.attendee.history'].create({
                'user': self.env.uid,
                'wf_task_history': task_history.id,
                'action': 'pass'
            })
            # 更新execution和instance状态
            self.workflow_instance.wf_executions[-1].update({'status': 'pass',
                                                             'status_owner': self.env.uid,
                                                             'is_complete': True})
            self.workflow_instance.write({'status': 'pass',
                                          'status_owner': self.env.uid,
                                          'is_complete': True})
        else:
            # 更新execution和instance的值
            workflow_status = WorkflowStatus(self.workflow_instance, self.env, sub_workflow)
            execution_status = workflow_status.compute_execution_status()
            # 最后一个execution是当前在执行的
            self.workflow_instance.wf_executions[-1].update(
                {'status': execution_status.get('status'),
                 'status_owner': execution_status.get('status_owner')})
            instance_status = workflow_status.compute_instance_status()
            self.workflow_instance.write({'status': instance_status.get('status'),
                                          'status_owner': instance_status.get('status_owner')})

        # 自动预处理下一个任务
        self.do_auto_operation(self.workflow_instance.wf_executions[0])
        # 通知审批者
        self.alert_next_approver(self.workflow_instance.id)

    # 提取创建task attendee部分，方便外部扩展使用
    def build_task_attendee_data(self, task_attendee_data):
        task_attendee = []
        for user in task_attendee_data:
            task_attendee.append((0, 0, {'user': user[0]}))
        return task_attendee

    def do_submit(self, **kwargs):
        """
        调用此方法，提交审批
        """
        try:
            wf_instance = kwargs['instance']
            model = kwargs['model']
            record = kwargs['record']

            logger.info("%s submit for approval", self.env.user.login)
            if wf_instance:
                # 之前提交过，创建新的execution和task
                self.create_instance_init_data(model, record, wf_instance)
            else:
                # 第一次提交，创建instance，execution，task
                self.create_instance_init_data(model, record)
        except Exception as ex:
            # 处理审批引擎中的脚本节点raise的错误，如：raise Exception("未找到对应的审批人")
            # 根据引擎抛出对象的结构，只给mobile抛出对应错误信息。
            if (hasattr(ex, 'error_type') and hasattr(ex, 'args') and len(ex.args) > 0
                    and ex.args[0].startswith(ex.error_type + ':')):  # pylint: disable=E1101
                raise UserError(ex.args[0][len(ex.error_type + ':'):]) from ex  # pylint: disable=E1101
            raise ex

    @_snow_workflow_user_action
    def do_single_pass(self, **kwargs):
        """
        调用此方法，将当前所有处于Ready状态的**单人审批**工作流任务标记为审批**通过**，并完成。
        """
        task_name = kwargs['task_name']
        wf_instance = kwargs['instance']
        auto_handle = kwargs['auto_handle'] if 'auto_handle' in kwargs else False
        task = self.get_task_from_name(task_name)
        task.set_data(current_task_id=str(task.id))

        user = kwargs['user'] if 'user' in kwargs else self.env.user
        logger.info("%s passed %s", user.login, str(task.id))

        task_data = {
            str(task.id): {
                'pass': user.id
            }
        }

        task.set_data(**task_data)
        return self._do_common_user_operation(wf_instance, task, 'pass', user=user,
                                              auto_handle=auto_handle)

    @_snow_workflow_user_action
    def do_single_reject(self, **kwargs):
        """
        调用此方法，将当前所有处于Ready状态的**单人审批**工作流任务标记为审批**拒绝**，并完成。
        """
        task_name = kwargs['task_name']
        wf_instance = kwargs['instance']
        auto_handle = kwargs['auto_handle'] if 'auto_handle' in kwargs else False
        task = self.get_task_from_name(task_name)
        task.set_data(current_task_id=str(task.id))

        user = kwargs['user'] if 'user' in kwargs else self.env.user
        logger.info("%s rejected %s", user.login, str(task.id))

        task_data = {
            str(task.id): {
                'reject': user.id
            }
        }

        task.set_data(**task_data)
        return self._do_common_user_operation(wf_instance, task, 'reject', user=user,
                                              auto_handle=auto_handle)

    @_snow_workflow_user_action
    def do_multi_pass(self, **kwargs):
        """
        调用此方法，将当前所有处于Ready状态的**组审批**工作流任务标记为审批**通过**，并完成。
        """
        task_name = kwargs['task_name']
        task = self.get_task_from_name(task_name)
        auto_handle = kwargs['auto_handle'] if 'auto_handle' in kwargs else False
        wf_instance = kwargs['instance']
        task.set_data(current_task_id=str(task.id))

        user = kwargs['user'] if 'user' in kwargs else self.env.user
        logger.info("%s passed %s in group approval", user.login, str(task.id))

        # 组审批或签
        if task.get_description() == 'group_approve_execution_or':
            return self._do_multi_common_or(wf_instance, task, 'pass', user=user,
                                            auto_handle=auto_handle)
        # 组审批会签
        if task.get_description() == 'group_approve_execution_and':
            return self._do_multi_common_and(wf_instance, task, 'pass', user=user,
                                             auto_handle=auto_handle)
        raise SnowWorkflowRuntimeError(
            f"do_multi method support: {GROUP_APPROVE_EXECUTION_TASKS}, current: {task.get_description()}"
        )

    @_snow_workflow_user_action
    def do_multi_reject(self, **kwargs):
        """
        调用此方法，将当前所有处于Ready状态的**组审批**工作流任务标记为审批**通过**，并完成。
        """
        task_name = kwargs['task_name']
        wf_instance = kwargs['instance']
        task = self.get_task_from_name(task_name)
        task.set_data(current_task_id=str(task.id))

        user = kwargs['user'] if 'user' in kwargs else self.env.user
        logger.info("%s passed %s in group approval", user.login, str(task.id))

        # 组审批或签
        if task.get_description() == 'group_approve_execution_or':
            return self._do_multi_common_or(wf_instance, task, 'reject', user=user)
        # 组审批会签
        if task.get_description() == 'group_approve_execution_and':
            return self._do_multi_common_and(wf_instance, task, 'reject', user=user)

        raise SnowWorkflowRuntimeError(
            "do_multi method support: {}, current: {}".format(GROUP_APPROVE_EXECUTION_TASKS,
                                                              task.get_description())
        )

    @_snow_workflow_user_action
    def do_withdraw(self, **kwargs):
        """
        调用此方法，将当前所有处于Ready状态的Approval UserTask(单人审批工作流任务)标记为**撤销审批**，并完成。
        """
        task_name = kwargs['task_name']
        wf_instance = kwargs['instance']
        task = self.get_task_from_name(task_name)
        task.set_data(current_task_id=str(task.id))

        logger.info("%s withdraw %s", self.env.user.login, str(task.id))

        task_data = {
            str(task.id): {
                'withdraw': self.env.uid
            }
        }

        task.set_data(**task_data)
        return self._do_common_user_operation(wf_instance, task, 'withdraw')

    @_snow_workflow_user_action
    def do_suspend(self, **kwargs):
        """
        调用此方法，将此工作流挂起
        """
        task_name = kwargs['task_name']
        task = self.get_task_from_name(task_name)
        logger.info("%s suspend %s", self.env.user.login, self.workflow_instance.id)

        # 当前工作流没有被挂起才操作
        if self.workflow_instance.status == "suspend":
            logger.warning(
                "Suspension failure, workflow_instance：%s is already suspended",
                self.workflow_instance.id
            )
            return

        # 新建suspend记录
        self.env['snow.workflow.instance.suspend'].create({
            'wf_instance': self.workflow_instance.id,
            'suspend_user': self.env.user.id,
            'suspend_time': datetime.datetime.now()
        })

        # 获取并更新最新的execution_record, erd: execution_record_data
        execution_record = self.workflow_instance.wf_executions[-1]
        erd = self.record_util.create_execution_record_static_data(
            self.workflow_instance, task.workflow
        )

        is_external_manager = self.env.uid in [
            manager.user_id.id for manager in
            self.workflow_instance.wf_definition.external_managers
        ]

        # 更新execution_record的vision数据
        erd.update({
            'vision_data': json.dumps(
                SnowWorkflowVision(self.env).update_user_action_to_vision_data(  # pylint: disable=E1101
                    json.loads(execution_record.vision_data), task, 'suspend',
                    is_external_manager=is_external_manager
                ),
                ensure_ascii=False
            )
        })

        execution_record.update(erd)

        # 更新instance的state信息
        self.update_instance_status()

    @_snow_workflow_user_action
    def do_unsuspend(self, **kwargs):
        """
        调用此方法，将当前已经挂起的工作流解除挂起状态
        """
        task_name = kwargs['task_name']
        task = self.get_task_from_name(task_name)
        logger.info("%s unsuspend %s", self.env.user.login, self.workflow_instance.id)

        # 当前工作流被挂起了才操作
        if self.workflow_instance.status != 'suspending':
            logger.warning(
                "Unsuspension failure，workflow_instance：%s is already unsuspended",
                self.workflow_instance.id
            )
            return

        # 查出suspend记录
        suspend_record = self.env['snow.workflow.instance.suspend'].sudo().search([
            ('wf_instance', '=', self.workflow_instance.id)
        ])
        if not suspend_record:
            logger.error(
                "Unsuspension failure，no suspend info for workflow_instance：%s",
                self.workflow_instance.id
            )
            return

        # 新建suspend_history记录
        suspend_start_time = suspend_record.suspend_time
        self.env['snow.workflow.instance.suspend.history'].create({
            'wf_instance': self.workflow_instance.id,
            'suspend_user': self.env.user.id,
            'suspend_time': suspend_start_time,
            'unsuspend_time': datetime.datetime.now()
        })

        # 删除此suspend记录
        suspend_record.unlink()

        # 获取并更新最新的execution_record
        execution_record = self.workflow_instance.wf_executions[-1]
        erd = self.record_util.create_execution_record_static_data(
            self.workflow_instance, task.workflow
        )

        is_external_manager = self.env.uid in [
            manager.user_id.id for manager in
            self.workflow_instance.wf_definition.external_managers
        ]

        # 更新execution_record的vision数据
        erd.update({
            'vision_data': json.dumps(
                SnowWorkflowVision(self.env).update_user_action_to_vision_data(  # pylint: disable=E1101
                    json.loads(execution_record.vision_data), task, 'unsuspend',
                    is_external_manager=is_external_manager
                ),
                ensure_ascii=False
            )
        })

        execution_record.update(erd)

        # 更新instance的state信息
        self.update_instance_status()

    @_snow_workflow_user_action
    def add_attendee(self, **kwargs):
        """
        调用此方法，做加签操作
        """
        # 给显示json添加一个节点
        task_name = kwargs['task_name']
        task = self.get_task_from_name(task_name)
        attendee_id = self.env.context.get('attendee_id')
        attendee_name = self.env.context.get('attendee_name')
        execution_record = self.workflow_instance.wf_executions[-1]
        task_record = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', self.workflow_instance.id), ('in_progress', '=', True)])
        execution_record.update({
            'vision_data': json.dumps(
                SnowWorkflowVision(self.env).add_node_to_vision_data(  # pylint: disable=E1101
                    json.loads(execution_record.vision_data),
                    task,
                    attendee_name),
                ensure_ascii=False
            )
        })
        # 在task attendee表增加一个审批人，标注is_assigner
        self.env['snow.workflow.execution.task.attendee'].create({
            'user': attendee_id,
            'wf_task': task_record.id,
            'is_assigner': True,
            'assigner_state': 0
        })

    def update_instance_status(self):
        status_info = WorkflowStatus(self.workflow_instance, self.env).compute_instance_status()
        self.workflow_instance.write({
            'status': status_info.get('status'),
            'status_owner': status_info.get('status_owner')
        })
        logger.info("workflow state updated to：%s", self.workflow_instance.status)

    def _do_common_user_operation(self, wf_instance, task, user_action=None, **kwargs):
        """
        用户对task执行了操作，要过一遍这个方法
        """
        # 对象、数据准备
        action_user = kwargs.get('user') if 'user' in kwargs else self.env.user
        auto_handle = kwargs.get('auto_handle')
        child_workflow = task.workflow  # 第一层子流程
        task_record = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', wf_instance), ('in_progress', '=', True)])
        execution_record = task_record.wf_execution
        instance_record = self.env['snow.workflow.instance'].browse(wf_instance)

        # 校验
        if child_workflow._get_outermost_workflow() is not self.main_workflow:
            raise SnowWorkflowValidationError("instance and execution are not matched.")

        node_finished = False
        if user_action == 'pass':
            # 常规审批者中，除了审批提交者，当前审批者，是否还有其他审批人存在
            regular_attendee = task_record.task_attendee.filtered(
                lambda r: r.user.id not in [instance_record.initiator.id,
                                            action_user.id] and not r.is_assigner)
            if len(regular_attendee) == 0 or task.get_description() == 'group_approve_execution_or':
                # 常规审批者已经审批完，判断是否有加签审批者  或者  该节点为一个或签节点
                additional_attendee = task_record.task_attendee.filtered(
                    lambda r: r.is_assigner and r.user.id != action_user.id).sorted(
                    key=lambda r: r.create_date, reverse=True)
                if len(additional_attendee) > 0:
                    # 有加签者，不推进工作流，更新加签人中第一个人状态为开始
                    additional_attendee[0].assigner_state = 1
                else:
                    # 已经是最后一个审批人，向下推进审批流
                    node_finished = True
        else:
            node_finished = True

        # 如果节点审批结束，推进审批流
        if node_finished:
            for item in self.main_workflow.get_tasks():
                if item.state != 64 and item.task_spec.spec_type == 'Script Task':
                    item.set_data(script_env=self.env)
            # task运行
            task.run()
            # 推进子流程
            child_workflow.do_engine_steps()
            # 子流程直接结束，无需外网关等配置
            self.main_workflow.refresh_waiting_tasks()
            self.main_workflow.do_engine_steps()

        self._do_db_operation(task_record, task, user_action, action_user, node_finished)

        if node_finished and user_action == 'pass':
            # 对下一个任务做预处理
            self.do_auto_operation(execution_record)
            if not auto_handle:
                # 预处理后给下个任务审批者发消息
                self.alert_next_approver(wf_instance)

    def alert_next_approver(self, wf_instance):
        # 通知demo，会在snow_common中做覆盖
        self.env['snow.workflow.notification'].send_message_to_approver(self.env.uid, '', '', '/')

    def do_auto_operation(self, execution_record):
        """
        用户动作后，对下一个任务进行自动预处理
        :return:
        """
        if self.workflow_instance.wf_definition.same_user_action == 'wait':
            # 根据配置 等待同一人审批 或 遇同一人自动审批
            return
        # 获取本条数据对历史审批情况
        attendee_pass_history = [
            history.user.id
            for execution in execution_record.wf_execution_tasks_history
            for history in execution.task_attendee_history
            if history.action == 'pass' and history.user.id
        ]
        # 获取当前激活任务
        current_task = self.env['snow.workflow.execution.task'].with_context(
            _type='').sudo().search(
            [('wf_execution', '=', execution_record.id), ('in_progress', '=', True)])
        attendee_list = [attendee.user for attendee in current_task.task_attendee if
                         attendee.user.id != self.workflow_instance.initiator.id]
        for user in attendee_list:
            # 下一任务如果是单人任务，审批者在历史审批者中，自动处理
            if (user.id in attendee_pass_history and
                    current_task.task_xml_name == 'approve_execution'):
                self.do_single_pass(instance=self.workflow_instance.id,
                                    task_name=current_task.task_xml_id,
                                    user=user, auto_handle=True)
            # 下一任务如果是组审批，调用组审批方法
            elif (user.id in attendee_pass_history and
                  current_task.task_xml_name in GROUP_APPROVE_EXECUTION_TASKS):
                self.do_multi_pass(instance=self.workflow_instance.id,
                                   task_name=current_task.task_xml_id, user=user,
                                   auto_handle=True)

    def _do_db_operation(self, task_record, task, user_action, user, node_finished):
        """
            执行任务后，通用数据库处理
        """
        wf_execution = task_record.wf_execution
        subprocess = list(self.main_workflow.subprocesses.values())[0]
        """
            处理 task_history_record 数据
        """
        task_history_record = self.env['snow.workflow.execution.task.history'].with_context(
            _type='').sudo().search(
            [('wf_task', '=', task_record.id)])
        if not task_history_record:
            task_history_record = self._do_db_operation_create_task_history(task_record, task)

        task_history_record.write(self.record_util.create_task_record_static_data(task))

        """
            创建task_attendee_history记录
        """
        if user_action == "withdraw":
            for attendee in task_record.task_attendee:
                self.env['snow.workflow.execution.task.attendee.history'].create({
                    'user': attendee.user.id,
                    'wf_task_history': task_history_record.id,
                    'action': user_action
                })
        else:
            self.env['snow.workflow.execution.task.attendee.history'].create({
                'user': user.id,
                'wf_task_history': task_history_record.id,
                'action': user_action
            })
        # 删除task数据前，更新task_data记录
        self.env['snow.workflow.execution.task.data'].sudo().search(
            [('wf_task', '=', task_record.id)]).write(
            {'wf_task_history': task_history_record.id})

        """
            清理本次审批数据
        """
        if node_finished:
            if user_action == 'pass':
                # 通过该节点，删除task，将下一个task激活
                task_record.unlink()
                # 根据 BPMN 引擎中实际 READY 的任务来激活 DB 记录，
                # 避免网关跳过的任务被按 DB id 顺序错误激活。
                # 注意：同一 BPMN 节点可能因多入边而产生多条 DB 记录，
                # 对每个任务名只激活第一条记录，防止多条同时 in_progress。
                for name in [t.get_name() for t in self.main_workflow.get_ready_user_tasks()]:
                    next_task = self.env['snow.workflow.execution.task'].with_context(
                        _type='').sudo().search(
                        [('wf_execution', '=', wf_execution.id),
                         ('task_xml_id', '=', name)], limit=1)
                    next_task.update({'in_progress': True})

            else:
                # 审批动作为：撤销或拒绝，删除所有生成的task
                self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
                    [('wf_execution', '=', task_record.wf_execution.id)]).unlink()
        else:
            # 审批节点没有结束，从attendee中删除该审批人
            self.env['snow.workflow.execution.task.attendee'].search(
                [('wf_task', '=', task_record.id),
                 ('user', '=', user.id)], limit=1, order='id').unlink()
        # 当前用户为外部管理者
        is_external_manager = user.id in [manager.user_id.id for manager in
                                          wf_execution.wf_instance.wf_definition.external_managers]
        """
            更新execution（视图数据vision_data 和 状态数据）
        """
        vision_data = json.loads(wf_execution.vision_data)
        if subprocess.is_completed():
            vision_data['state'] = 'complete'
        vision_data = SnowWorkflowVision(self.env).update_user_action_to_vision_data(  # pylint: disable=E1101
            vision_data,
            task,
            user_action,
            task_history_record.id,
            user=user,
            is_external_manager=is_external_manager
        )
        wf_execution.update({
            'vision_data': json.dumps(
                vision_data,
                ensure_ascii=False
            )
        })
        status_info = WorkflowStatus(wf_execution.wf_instance, self.env,
                                     subprocess).compute_execution_status()
        wf_execution.update({
            'wf_json': self.bpmn_workflow_engine.save_workflow_obj_to_json_str(self.main_workflow),
            'is_complete': subprocess.is_completed(),
            'status': status_info.get('status'),
            'status_owner': status_info.get('status_owner')
        })
        wf_execution.flush()

        """
            最后更新instance状态
        """
        status_info = WorkflowStatus(self.workflow_instance, self.env).compute_instance_status()
        self.workflow_instance.write({
            'is_complete': status_info.get('status') == 'pass',
            'status': status_info.get('status'),
            'status_owner': status_info.get('status_owner'),
            'end_time': datetime.datetime.now() if self.main_workflow.is_completed() else None
        })
        self.workflow_instance.flush()

        self.alert_submitter(wf_execution, user.name, user_action)

    def alert_submitter(self, wf_execution, user, user_action):
        # 通知demo，会在snow_common中做覆盖
        self.env['snow.workflow.notification'].send_message_to_submitter(self.env.uid, '', '', '/')

    def _do_db_operation_create_task_history(self, task_record, task):
        """
        根据task_record与task对象，创建task_history_record
        """
        # 根据task对象生成task_history_record的static数据
        task_history_record_data = self.record_util.create_task_history_record_static_data(
            task_record.id, task)
        # 使用task_record填充task_history_record的relation-m2o数据
        task_history_record_data.update({
            'wf_execution': task_record.wf_execution.id
        })

        return self.env['snow.workflow.execution.task.history'].with_context(
            _type='').sudo().create(
            task_history_record_data)

    def _do_multi_common_and(self, wf_instance, task, user_action, **kwargs):
        """
        会签的common方法
        """
        user = kwargs['user'] if 'user' in kwargs else self.env.user
        auto_handle = kwargs['auto_handle'] if 'auto_handle' in kwargs else False
        task_action_data = task.data.get(str(task.id))

        # 写task数据, 注意不要用set_data()方法, 会覆盖task里的用户操作数据
        if task_action_data is None:
            task.data[str(task.id)] = {user_action: [user.id]}
        else:
            task_action_detail_data = task_action_data.get(user_action)

            if task_action_detail_data is None:
                task.data[str(task.id)][user_action] = [user.id]
            else:
                task_action_detail_data.append(user.id)

        # 先根据当前的task的id，在数据库中查所需数据
        tr = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', wf_instance), ('in_progress', '=', True)])
        thr = self.env['snow.workflow.execution.task.history'].with_context(_type='').sudo().search(
            [('wf_execution', '=', tr.wf_execution.id), ('task_xml_id', '=', tr.task_xml_id)])

        # 获取task的参与人user_ids
        # ta_user_ids = TaskAttendee(self.env).attendee_data_to_user_ids(tr.task_attendee.domain)

        # **根据人数**判断会签任务是否需要完成, len(thr.task_attendee_history) + 2: 把当前操作人、审批提交人也加上去

        # todo 后续删除此逻辑
        complete_flag = len(tr.task_attendee) <= (len(thr.task_attendee_history) + 2)  # pylint: disable=W0612

        if user_action == 'reject':
            complete_flag = True

        self._do_common_user_operation(wf_instance, task, user_action, user=user,
                                       auto_handle=auto_handle)

    def _do_multi_common_or(self, wf_instance, task, user_action, **kwargs):
        """
        或签的common方法
        """
        # 由于_do_common_user_operation会删除当前task_record, 这里需要在删除之前保存与之关联的task_attendee信息
        user = kwargs['user'] if 'user' in kwargs else self.env.user
        auto_handle = kwargs['auto_handle'] if 'auto_handle' in kwargs else False
        task_record = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', wf_instance), ('in_progress', '=', True)])
        user_ids = []
        for attendee in task_record.task_attendee:
            user_ids.append(attendee.user.id)

        task_data = {
            str(task.id): {
                user_action: user.id
            }
        }

        task.set_data(**task_data)
        self._do_common_user_operation(wf_instance, task, user_action, user=user,
                                       auto_handle=auto_handle)

        # 补充或签参与者的TaskAttendeeHistory的记录
        thr = self.env['snow.workflow.execution.task.history'].with_context(_type='').sudo().search(
            [('wf_task', '=', task_record.id)])

        tah_record_list = list()
        for uid in user_ids:
            if uid == user.id:
                continue

            # 过滤审批提交人
            if uid == self.workflow_instance.initiator.id:
                continue

            tah_record_list.append({
                'user': uid,
                'wf_task_history': thr.id,
                'action': user_action
            })

        if tah_record_list:
            self.env['snow.workflow.execution.task.attendee.history'].sudo().create(tah_record_list)

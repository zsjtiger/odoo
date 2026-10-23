from ..gluon.task import TaskState
from . import APPROVE_EXECUTION_TASKS, GROUP_APPROVE_EXECUTION_TASKS
from .exceptions import SnowWorkflowStatusAnalyzeError, SnowWorkflowValidationError


class WorkflowStatus(object):
    def __init__(self, workflow_instance=None, env=None, workflow=None):
        self.workflow_instance = workflow_instance
        self.env = env
        self.workflow = workflow

    def compute_execution_status(self):
        """
        计算所有sub_process的状态
        """
        # 先检查挂起状态
        if self.workflow_instance is not None:
            if self.workflow_instance.suspend_info:
                return {'status': 'suspending', 'status_owner': self.workflow_instance.suspend_info.suspend_user.id}

        # 检查workflow是否已经完成
        if self.workflow.is_completed():
            return self.compute_execution_status_on_completed()
        else:
            return self.compute_execution_status_on_uncompleted()

    def compute_instance_status(self):
        """
        根据workflow中的所有sub_workflow，计算workflow的状态
        """
        # 先检查【挂起】
        if self.workflow_instance.suspend_info:
            return {'status': 'suspending', 'status_owner': self.workflow_instance.suspend_info.suspend_user.id}

        # instance的状态，就是最后一次execution的状态
        execution_records = self.workflow_instance.wf_executions
        return {'status': execution_records[-1].status, 'status_owner': execution_records[-1].status_owner.id}

    def compute_execution_status_on_completed(self):
        """
        综合execution中的所有task的action data，计算execution的complete_state_flag
        :return:
        """
        action_datas = self.workflow.last_task.data

        all_action_list = []
        for action in action_datas.values():
            if isinstance(action, dict):
                all_action_list.extend(action.keys())
            else:
                continue

        pass_counter = 0
        reject_counter = 0
        withdraw_counter = 0
        for action in all_action_list:
            if action == 'withdraw':
                withdraw_counter += 1
            elif action == 'reject':
                reject_counter += 1
            elif action == 'pass':
                pass_counter += 1
            else:
                continue

        if withdraw_counter:  # 有撤销，则返回撤销
            self.workflow.set_data(complete_state_flag='withdraw')
            return {'status': 'withdraw', 'status_owner': self.workflow_instance.initiator.id}
        elif reject_counter:  # 有拒绝，则返回拒绝
            self.workflow.set_data(complete_state_flag='reject')
            # 拒绝状态，获取当前execution下最后一个被拒绝的任务审批人
            attendee = self.workflow_instance.wf_executions.filtered(lambda r: not r.is_complete)[
                0].wf_execution_tasks_history[-1].task_attendee_history.filtered(lambda r: r.action == 'reject')
            return {'status': 'reject', 'status_owner': attendee.user.id}
        elif pass_counter:  # 没有拒绝，有通过，则返回通过
            self.workflow.set_data(complete_state_flag='pass')
            # 通过状态，获取当前execution最后一个任务，多人任务不处理，单人任务返owner
            last_task = self.workflow_instance.wf_executions.filtered(lambda r: not r.is_complete)[
                0].wf_execution_tasks_history[-1]
            attendee = last_task.task_attendee_history
            if len(attendee) > 1 or (hasattr(last_task, 'task_xml_name')
                                     and getattr(last_task, 'task_xml_name') in GROUP_APPROVE_EXECUTION_TASKS):
                return {'status': 'pass', 'status_owner': None}
            else:
                return {'status': 'pass', 'status_owner': attendee.user.id}
        else:  # 没有拒绝，没有通过，没有撤回，抛异常
            raise SnowWorkflowValidationError("The approval flow ended abnormally")

    def compute_execution_status_on_uncompleted(self):
        all_tasks = self.workflow.get_tasks()

        # 检查是否有审批未完成
        approve_execution_cl = [
            t for t in all_tasks
            if t.get_description() in APPROVE_EXECUTION_TASKS
            and t.state in [TaskState.FUTURE, TaskState.READY]
        ]

        if approve_execution_cl:
            # 状态为审批中，获得当前execution下，正在进行的task的非提交者的attendee，如果组审批不处理，单节点返回为status_owner
            tasks = self.workflow_instance.wf_executions.filtered(lambda r: not r.is_complete)[
                0].wf_execution_tasks
            current_attendee = tasks.filtered(lambda r: r.in_progress).task_attendee.filtered(
                lambda r: r.user.id != self.workflow_instance.initiator.id)
            if len(current_attendee) > 1:
                return {'status': 'approve_pending', 'status_owner': None}
            else:
                user_id = current_attendee.user.id if current_attendee.user.id else None
                return {'status': 'approve_pending', 'status_owner': user_id}
        else:
            raise SnowWorkflowStatusAnalyzeError  # 都不匹配，抛状态分析异常

import datetime

from odoo import _
from .exceptions import SnowWorkflowRuntimeError
from . import GROUP_APPROVE_EXECUTION_TASKS


class SnowWorkflowVision:
    """
    SnowWorkflowVision的标准接口
    """
    proxy_cls = None

    def __new__(cls, *args, **kwargs):
        return cls.proxy_cls(*args, **kwargs)  # pylint: disable=E1102


class SnowWorkflowVisionMeta(type):
    def __new__(meta, name, bases, attrs):
        cls = super().__new__(meta, name, bases, attrs)
        # 发生继承时，自动更新SnowWorkflowVision的proxy，确保访问的是最新的类
        SnowWorkflowVision.proxy_cls = cls
        return cls


class SnowWorkflowBaseVision(metaclass=SnowWorkflowVisionMeta):
    def __init__(self, env):
        self.env = env

    def init_vision_data(self, submitter, submit_comment, vision_data, **kwargs):
        """
        初始化一个execution的vision数据

        :param submitter: snow.workflow.instance的initiator字段, 提交人
        :param submit_comment: 提交确认信息
        :param vision_data: 提交审批时，生成所有task数据
        :return: dict
        """
        init_data = {
            'submitter': submitter.name,
            'create_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'state': 'approve_draft',
            'approve_roadmap': [{
                'group_type': 'no',
                'task_name': 'submit',
                'state': 'submit',
                'members': [{
                    'create_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'actor': submitter.name,
                    'comments': submit_comment,
                    'state': 'submit'
                }]
            }]
        }
        first_task = True
        for data in vision_data:
            state = 'ready' if first_task else 'wait'
            first_task = False
            members = []
            for member in data['members']:
                members.append({
                    "create_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "actor": member[1],
                    "comments": "",
                    "state": state
                })
            group_type = self._get_group_type(data['task_type'])
            init_data['approve_roadmap'].append({
                "group_type": group_type,
                "task_name": data['task_name'],
                "state": self._compute_node_state(group_type, members),
                "members": members
            })
        if len(vision_data) == 0:
            # 初始化时无后续节点，为自审批，审批流程图中增加自审批节点
            init_data['approve_roadmap'].append({
                'group_type': 'no',
                'task_name': 'self_approval',
                'state': 'pass',
                'members': [{
                    'create_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'actor': submitter.name,
                    'comments': _('self approval'),
                    'state': 'pass'
                }]
            })

        return init_data

    def _get_task_comment(self, **kwargs):
        task_history_id = kwargs.get('task_history_id') if 'task_history_id' in kwargs else ''
        user = kwargs.get('user') if 'user' in kwargs else self.env.uid
        search_condition = []
        if task_history_id:
            search_condition.append(('wf_task_history', '=', task_history_id))
        if user:
            search_condition.append(('data_owner', '=', user))
        comment = self.env['snow.workflow.execution.task.data'].sudo().search(
            search_condition, limit=1).value
        return comment if comment else ''

    @staticmethod
    def _get_group_type(task_name):
        group_type = 'no'
        if task_name == 'group_approve_execution_or':
            group_type = 'or'
        elif task_name == 'group_approve_execution_and':
            group_type = 'and'
        return group_type

    @staticmethod
    def _compute_node_state(group_type, members):
        if not members:
            return 'wait'
        if group_type == 'no':
            return members[0]['state']
        if any(item.get('state') == 'reject' for item in members):
            return 'reject'
        if group_type in ['and', 'or'] and all(item.get('state') == 'wait' for item in members):
            return 'wait'
        if group_type == 'and' and all(item.get('state') == 'pass' for item in members):
            return 'pass'
        if group_type == 'or' and any(item.get('state') == 'pass' for item in members):
            return 'pass'
        return 'ready'

    @staticmethod
    def find_task_index(approve_roadmap, task, actor):
        """
        找到任务在roadmap中到坐标
        :param approve_roadmap:
        :param task:
        :return:
        """
        for index, item in enumerate(approve_roadmap):
            if ('task_name' in item and item['task_name'] == task.get_name() and
                    any(member["actor"] == actor for member in item['members'])):
                return index
        return False

    @staticmethod
    def find_task_index_by_state(approve_roadmap, state):
        """
        根据状态找到节点中第一个为该状态的坐标
        :param approve_roadmap:
        :param state:
        :return:
        """
        for index, item in enumerate(approve_roadmap):
            if 'state' in item and item['state'] == state:
                return index
        return False

    @staticmethod
    def set_next_node_state(next_node, from_state, to_state):
        for next_task_member in next_node['members']:
            if next_task_member['state'] == from_state:
                next_task_member['state'] = to_state
        next_node['state'] = to_state

    @staticmethod
    def set_nodes_state(target_index, approve_roadmap, state):
        for index in range(target_index + 1, len(approve_roadmap)):
            approve_roadmap[index]['state'] = state
            for member in approve_roadmap[index]['members']:
                member['state'] = state

    @staticmethod
    def set_other_members_finished(members, current_member):
        for node_member in members:
            if node_member != current_member:
                node_member['state'] = 'finished'
                node_member['create_date'] = ''

    def insert_node(self, approve_roadmap, index, user_action, **kwargs):
        user_name = kwargs['user_name'] if 'user_name' in kwargs else self.env.user.name
        task_name = kwargs['task_name'] if 'task_name' in kwargs else user_action
        group_type = kwargs['group_type'] if 'group_type' in kwargs else 'no'
        comment = kwargs['comment'] if 'comment' in kwargs else ''
        node = {
            'group_type': group_type,
            'task_name': task_name,
            'state': user_action,
            "members": [{
                "create_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "actor": user_name,
                "comments": comment,
                "state": user_action
            }]
        }
        approve_roadmap.insert(index, node)

    def update_user_action_to_vision_data(self, vision_data, task, user_action, task_id=None,
                                          **kwargs):
        """
        将用户的操作更新到vision_data中

        :param vision_data: dict格式的vision_data
        :param task: 当前task
        :param user_action: 用户的操作
        :param task_id: 任务id
        :return: json字符串
        """
        approve_roadmap = vision_data.get('approve_roadmap')
        group_type = self._get_group_type(task.get_description())
        user = kwargs.get('user') if 'user' in kwargs else self.env.user
        is_external_manager = kwargs.get(
            'is_external_manager') if 'is_external_manager' in kwargs else False

        # 校验
        if approve_roadmap is None:
            raise SnowWorkflowRuntimeError('vision data error, there is no approve_roadmap object')

        # 用户操作通过、拒绝, 则**更新**member信息
        if user_action in ['pass', 'reject']:  # pylint: disable=R1702
            find_node = False
            for index, value in enumerate(approve_roadmap):
                if 'task_name' in value and value['task_name'] == task.get_name():
                    for member in value['members']:
                        if member['actor'] == user.name or (
                                member['actor'] == 'empty' and not user.name):
                            find_node = True
                            member['create_date'] = datetime.datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S")
                            member['state'] = user_action
                            member['comments'] = self._get_task_comment(task_history_id=task_id,
                                                                        user=user.id)
                            # 更新整个节点状态
                            node_state = self._compute_node_state(group_type, value['members'])
                            value['state'] = node_state
                            # 更新同组其他审批者状态
                            if (node_state == 'pass' and
                                    task.get_description() == 'group_approve_execution_or'):
                                # 或签一人通过，更新其他用户状态
                                self.set_other_members_finished(value['members'], member)
                            elif (node_state == 'reject' and
                                  task.get_description() in GROUP_APPROVE_EXECUTION_TASKS):
                                # 组审批一人拒绝，更新其他用户状态
                                self.set_other_members_finished(value['members'], member)
                            # 更新后续节点状态
                            if index + 1 < len(approve_roadmap) and node_state == 'pass':
                                # 单节点通过，将下一节点从 wait 设为 ready
                                self.set_next_node_state(approve_roadmap[index + 1], 'wait',
                                                         'ready')
                            elif index + 1 < len(approve_roadmap) and node_state == 'reject':
                                # 拒绝，如果后续还有节点
                                self.set_nodes_state(index, approve_roadmap, 'finished')
            if not find_node and is_external_manager and user_action == 'reject':
                # 当前审批用户在外部审批者中，并且不在内部审批节点中，插入拒绝节点
                target_index = self.find_task_index_by_state(approve_roadmap, 'ready')
                if target_index:
                    comment = self._get_task_comment(task_history_id=task_id, user=user.id)
                    self.insert_node(approve_roadmap, target_index, 'reject', comment=comment)
                    self.set_nodes_state(target_index, approve_roadmap, 'finished')
        elif user_action == 'withdraw':
            # 找到当前任务所在节点坐标
            target_index = self.find_task_index_by_state(approve_roadmap, 'ready')
            if target_index:
                # 插入撤销节点
                self.insert_node(approve_roadmap, target_index, 'withdraw')
                # 更新后续节点状态为已结束
                self.set_nodes_state(target_index, approve_roadmap, 'finished')
        elif user_action in ['suspend', 'unsuspend']:
            if is_external_manager:
                if user_action == 'suspend':
                    target_index = self.find_task_index_by_state(approve_roadmap, 'ready')
                else:
                    target_index = self.find_task_index_by_state(approve_roadmap, 'wait')
            else:
                # 找到当前任务所在节点坐标
                target_index = self.find_task_index(approve_roadmap, task, self.env.user.name)
            if target_index:
                # 插入状态节点
                self.insert_node(approve_roadmap, target_index, user_action)
                if user_action == 'suspend':
                    self.set_next_node_state(approve_roadmap[target_index + 1], 'ready', 'wait')
                else:
                    self.set_next_node_state(approve_roadmap[target_index + 1], 'wait', 'ready')

        return vision_data

    def add_node_to_vision_data(self, vision_data, task, assigner):
        # 从现有json中找到插入位置
        approve_roadmap = vision_data.get('approve_roadmap')
        target_index = self.find_task_index(approve_roadmap, task, self.env.user.name)
        if target_index:
            # 插入撤销节点
            self.insert_node(approve_roadmap,
                             target_index + 1,
                             'wait',
                             user_name=assigner,
                             task_name=task.get_name(),
                             group_type='add')
        return vision_data

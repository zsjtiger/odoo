import re
import logging

from .exceptions import SnowWorkflowValidationError, SnowWorkflowAttendeeLaneAnalyzeError, SnowWorkflowRuntimeError
from odoo.tools import html_escape


logger = logging.getLogger(__name__)


class TaskAttendee(object):
    analyze_classes = dict()

    def __init__(self, env=None):
        self.env = env

    @staticmethod
    def add_attendee_info(user_id_set, user):
        user_id_set.add((user.id, user.name))

    def lane_to_attendee_data(self, lane, submitter, task_data=None):
        """
        检查lane配置是否有效，并将lane转换成user数据

        :param lane: str
        :param submitter: 这里就是snow.workflow.instance的initiator字段值
        :param task_data: 脚本决定审批人时，需要从任务数据中获取脚本返回值
        :return: dict
        """
        if lane is None:
            raise SnowWorkflowValidationError("The approval task node cannot be empty")

        if '%(' in lane:
            variables = re.findall(r'%\((\w+)\)s', lane)
            for variable in variables:
                if variable in task_data:
                    lane = lane % {variable: task_data[variable]}
                else:
                    raise SnowWorkflowValidationError("The lane has a define variable")
        lane_dict = eval(lane)
        user_list = []

        attendee_data = dict()
        # 判断analyze_class种类，进行解析
        for anc_name in lane_dict.keys():
            if anc_name not in self.analyze_classes.keys():
                raise SnowWorkflowAttendeeLaneAnalyzeError(f"Can not analyse {anc_name}, supported: {self.analyze_classes.keys()}")

            anc = self.analyze_classes[anc_name](self.env)

            # 调用lane转user数据的不同实现
            # result = anc.analyze_lane(lane_dict[anc_name], submitter_id, task_data)   分析lane带入脚本参数
            result = anc.analyze_attendee_data(lane_dict[anc_name], submitter, task_data)
            for user in result:
                user_list.append(user)
        return user_list

    def is_executable_for_multi_approve_and(self, task_record) -> bool:
        """
        当前用户是否可以参与会签审批
        """
        if task_record.task_xml_name != 'group_approve_execution_and':
            return False

        task_attendee_history_records = self.env['snow.workflow.execution.task.history'].with_context(_type='').sudo().search([('wf_task', '=', task_record.id)]).task_attendee_history

        if not task_attendee_history_records:
            return True

        return False if self.env.uid in [record.user.id for record in task_attendee_history_records] else True


class TaskAttendeeMeta(type):
    def __new__(meta, name, bases, attrs):
        # 创建此类
        cls = super().__new__(meta, name, bases, attrs)

        # 获取analyze_class_name, 登记到TaskAttendee接口中
        TaskAttendee.analyze_classes[attrs.get('analyze_class_name')] = cls
        if hasattr(cls, 'add_attendee_info'):
            TaskAttendee.add_attendee_info = cls.add_attendee_info
        return cls


class TaskAttendeeBase(metaclass=TaskAttendeeMeta):
    analyze_class_name = 'base'

    def analyze_attendee_data(self, content, submitter, task_data=None):
        raise NotImplementedError


class TaskAttendeeUser(TaskAttendeeBase):
    analyze_class_name = 'user'

    def __init__(self, env=None):
        self.env = env

    def analyze_attendee_data(self, content, submitter, task_data=None):
        user_ids_set = set()

        # submitter
        if isinstance(content, str):
            if content != 'submitter':
                raise SnowWorkflowValidationError(f'analyze_class:{self.analyze_class_name} can not support {content}')
            else:
                TaskAttendee.add_attendee_info(user_ids_set, submitter)
        # domain
        elif isinstance(content, dict):
            if not (len(content.keys()) == 1 and 'domain' in content.keys()):
                raise SnowWorkflowValidationError(f'analyze_class:{self.analyze_class_name} can not support {content}')
            else:
                content['domain'].extend(['|', ('active', '=', True), ('active', '=', False)])
                for record in self.env['res.users'].sudo().search(content['domain']):
                    TaskAttendee.add_attendee_info(user_ids_set, record)
        # 其他
        else:
            raise SnowWorkflowAttendeeLaneAnalyzeError(f'analyze_class:{self.analyze_class_name} can not support {content}')

        return list(user_ids_set)


class TaskAttendeeScript(TaskAttendeeBase):
    analyze_class_name = 'script'

    def __init__(self, env=None):
        self.env = env

    def analyze_attendee_data(self, content, submitter, task_data=None):
        """
        {'script': {'key': 'script_users'}}
        """
        user_ids_set = set()

        if isinstance(content, dict):
            if not (len(content.keys()) == 1 and 'key' in content.keys()):
                raise SnowWorkflowValidationError(f'analyze_class:{self.analyze_class_name} can not support {content}')
            else:
                for user in task_data[content['key']]:
                    TaskAttendee.add_attendee_info(user_ids_set, user)
        # 其他
        else:
            raise SnowWorkflowAttendeeLaneAnalyzeError(f'analyze_class:{self.analyze_class_name} can not support {content}')

        return list(user_ids_set)

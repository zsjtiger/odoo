# Copyright 2023 The CrossNow.inc Authors.
#

from ...bpmn.parser.event_parsers import SendTaskParser
from ...camunda.parser.task_spec import CamundaTaskParser


class CamundaSendTaskParser(SendTaskParser, CamundaTaskParser):
    """
    sendTask: camunda:property targetRecord 给出目标记录表达式 (可选), 消息本身仍按 bpmn 解析
    """

    def create_task(self):
        task = SendTaskParser.create_task(self)
        task.target_record = self.parse_extensions().get('targetRecord') or None
        return task

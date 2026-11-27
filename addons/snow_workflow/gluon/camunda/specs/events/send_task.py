# Copyright 2023 The CrossNow.inc Authors.
#

from copy import deepcopy

from ....bpmn.specs.events.IntermediateEvent import SendTask
from ....bpmn.specs.events.event_definitions import MessageEventDefinition
from ....bpmn.workflow import BpmnMessage

# 消息关联中记录目标业务记录的键
TARGET_RECORD_KEY = 'target_record'
# 流程数据中不随消息发送的键: 运行环境与接收方的业务记录引用不能被覆盖
NOT_SENT_KEYS = ('script_env', 'model', 'record')


class CrossRecordSendTask(SendTask):
    """
    发送消息任务。设置了 target_record 表达式时，消息带上目标记录并发往流程外，
    由业务模块投递给同模型、同记录号的正在等待该消息的流程；未设置时与普通发送任务一致。
    """

    def __init__(self, wf_spec, name, event_definition, target_record=None, **kwargs):
        super().__init__(wf_spec, name, event_definition, **kwargs)
        self.target_record = target_record

    def _run_hook(self, my_task):
        if not self.target_record or not isinstance(self.event_definition, MessageEventDefinition):
            return super()._run_hook(my_task)
        workflow = my_task.workflow
        target = workflow.script_engine.evaluate(my_task, self.target_record)
        payload = deepcopy({k: v for k, v in my_task.data.items() if k not in NOT_SENT_KEYS})
        correlations = self.event_definition.get_correlations(my_task, payload)
        workflow.correlations.update(correlations)
        # 带目标的消息一定发往流程外, 不在本流程内被接收任务消费
        outermost = workflow._get_outermost_workflow()
        outermost.bpmn_messages.append(
            BpmnMessage(dict(correlations, **{TARGET_RECORD_KEY: target}), self.event_definition.name, payload))
        return True

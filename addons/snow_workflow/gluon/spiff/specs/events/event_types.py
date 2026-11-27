# Copyright 2023 The CrossNow.inc Authors.
#

from ..spiff_task import SpiffBpmnTask
from ....bpmn.specs.events.IntermediateEvent import SendTask, ReceiveTask

class SendTask(SendTask, SpiffBpmnTask):
    pass

class ReceiveTask(ReceiveTask, SpiffBpmnTask):
    pass
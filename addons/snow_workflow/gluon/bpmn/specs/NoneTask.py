# Copyright 2023 The CrossNow.inc Authors.
#

from ...specs.Simple import Simple
from ...bpmn.specs.BpmnSpecMixin import BpmnSpecMixin


class NoneTask(Simple, BpmnSpecMixin):

    def is_engine_task(self):
        return False

    @property
    def spec_type(self):
        return 'Task'

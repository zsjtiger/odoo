# Copyright 2023 The CrossNow.inc Authors.
#

from ...bpmn.specs.BpmnSpecMixin import BpmnSpecMixin
from ...specs.Simple import Simple


class ManualTask(Simple, BpmnSpecMixin):

    def is_engine_task(self):
        return False

    @property
    def spec_type(self):
        return 'Manual Task'

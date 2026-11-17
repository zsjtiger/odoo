# Copyright 2023 The CrossNow.inc Authors.
#

from .BpmnSpecMixin import BpmnSpecMixin
from ...specs.Simple import Simple


class UserTask(Simple, BpmnSpecMixin):

    """
    Task Spec for a bpmn:userTask node.
    """

    def is_engine_task(self):
        return False

    @property
    def spec_type(self):
        return 'User Task'
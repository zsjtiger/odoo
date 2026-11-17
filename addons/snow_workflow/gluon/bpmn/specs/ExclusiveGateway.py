# Copyright 2023 The CrossNow.inc Authors.
#

from .BpmnSpecMixin import BpmnSpecMixin
from ...specs.ExclusiveChoice import ExclusiveChoice
from ...specs.MultiChoice import MultiChoice


class ExclusiveGateway(ExclusiveChoice, BpmnSpecMixin):
    """
    Task Spec for a bpmn:exclusiveGateway node.
    """

    def test(self):
        # Bypass the check for no default output -- this is not required in BPMN
        MultiChoice.test(self)

    @property
    def spec_type(self):
        return 'Exclusive Gateway'

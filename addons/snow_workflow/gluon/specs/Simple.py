# Copyright 2023 The CrossNow.inc Authors.
#

from .base import TaskSpec


class Simple(TaskSpec):

    """
    This class implements a task with one or more inputs and
    any number of outputs.
    If more than one input is connected, the task performs an implicit
    multi merge.
    If more than one output is connected, the task performs an implicit
    parallel split.
    """

    def serialize(self, serializer):
        return serializer.serialize_simple(self)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_simple(wf_spec, s_state)

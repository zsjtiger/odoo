# Copyright 2023 The CrossNow.inc Authors.
#

from .Trigger import Trigger


class CancelTask(Trigger):

    """
    This class implements a trigger that cancels another task (branch).
    If more than one input is connected, the task performs an implicit
    multi merge.
    If more than one output is connected, the task performs an implicit
    parallel split.
    """

    def _run_hook(self, my_task):
        for task_name in self.context:
            cancel_tasks = my_task.workflow.get_task_spec_from_name(task_name)
            for cancel_task in my_task._get_root()._find_any(cancel_tasks):
                cancel_task.cancel()
        return True

    def serialize(self, serializer):
        return serializer.serialize_cancel_task(self)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_cancel_task(wf_spec, s_state)

# Copyright 2023 The CrossNow.inc Authors.
#

from ..task import TaskState
from .base import TaskSpec
from ..operators import valueof


class MultiInstance(TaskSpec):

    """
    When executed, this task performs a split on the current task.
    The number of outgoing tasks depends on the runtime value of a
    specified data field.
    If more than one input is connected, the task performs an implicit
    multi merge.

    This task has one or more inputs and may have any number of outputs.
    """

    def __init__(self, wf_spec, name, times, **kwargs):
        """
        Constructor.

        :type  wf_spec: WorkflowSpec
        :param wf_spec: A reference to the workflow specification.
        :type  name: str
        :param name: The name of the task spec.
        :type  times: int or :class:`gluon.operators.Term`
        :param times: The number of tasks to create.
        :type  kwargs: dict
        :param kwargs: See :class:`gluon.specs.TaskSpec`.
        """
        if times is None:
            raise ValueError('times argument is required')
        TaskSpec.__init__(self, wf_spec, name, **kwargs)
        self.times = times

    def _find_my_task(self, task):
        for thetask in task.workflow.task_tree:
            if thetask.thread_id != task.thread_id:
                continue
            if thetask.task_spec == self:
                return thetask
        return None

    def _on_trigger(self, task_spec):
        """
        May be called after execute() was already completed to create an
        additional outbound task.
        """
        # Find a Task for this TaskSpec.
        my_task = self._find_my_task(task_spec)
        if my_task._has_state(TaskState.COMPLETED):
            state = TaskState.READY
        else:
            state = TaskState.FUTURE
        for output in self.outputs:
            new_task = my_task._add_child(output, state)
            new_task.triggered = True
            output._predict(new_task, mask=TaskState.FUTURE|TaskState.READY|TaskState.PREDICTED_MASK)

    def _get_predicted_outputs(self, my_task):
        split_n = int(valueof(my_task, self.times, 1))
        return self.outputs * split_n

    def _predict_hook(self, my_task):
        outputs = self._get_predicted_outputs(my_task)
        if my_task._is_definite():
            my_task._sync_children(outputs, TaskState.FUTURE)
        else:
            my_task._sync_children(outputs, TaskState.LIKELY)

    def _run_hook(self, my_task):
        outputs = self._get_predicted_outputs(my_task)
        my_task._sync_children(outputs, TaskState.FUTURE)
        self._predict(my_task, mask=TaskState.FUTURE|TaskState.PREDICTED_MASK)
        return True

    def serialize(self, serializer):
        return serializer.serialize_multi_instance(self)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_multi_instance(wf_spec, s_state)

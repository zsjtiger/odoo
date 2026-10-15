# Copyright 2023 The CrossNow.inc Authors.
#

from ..exceptions import WorkflowException
from .base import TaskSpec


class Cancel(TaskSpec):

    """
    This class cancels a complete workflow.
    If more than one input is connected, the task performs an implicit
    multi merge.
    If more than one output is connected, the task performs an implicit
    parallel split.
    """

    def __init__(self, wf_spec, name, success=False, **kwargs):
        """
        Constructor.

        :type  wf_spec: WorkflowSpec
        :param wf_spec: A reference to the workflow specification.
        :type  name: str
        :param name: The name of the task spec.
        :type  success: bool
        :param success: Whether to cancel successfully or unsuccessfully.
        :type  kwargs: dict
        :param kwargs: See :class:`gluon.specs.TaskSpec`.
        """
        TaskSpec.__init__(self, wf_spec, name, **kwargs)
        self.cancel_successfully = success

    def test(self):
        """
        Checks whether all required attributes are set. Throws an exception
        if an error was detected.
        """
        TaskSpec.test(self)
        if len(self.outputs) > 0:
            raise WorkflowException('Cancel with an output.', task_spec=self)

    def _run_hook(self, my_task):
        my_task.workflow.cancel(self.cancel_successfully)
        return True

    def serialize(self, serializer):
        return serializer.serialize_cancel(self)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_cancel(wf_spec, s_state)

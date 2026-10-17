# Copyright 2023 The CrossNow.inc Authors.
#
from ..exceptions import WorkflowException
from .base import TaskSpec


class StartTask(TaskSpec):

    """
    This class implements the task the is placed at the beginning
    of each workflow. The task has no inputs and at least one output.
    If more than one output is connected, the task does an implicit
    parallel split.
    """

    def __init__(self, wf_spec, name='Start', **kwargs):
        """
        Constructor. The name of this task is *always* 'Start'.

        :type  wf_spec: WorkflowSpec
        :param wf_spec: A reference to the workflow specification.
        :type  kwargs: dict
        :param kwargs: See :class:`gluon.specs.TaskSpec`.
        """
        TaskSpec.__init__(self, wf_spec, name, **kwargs)

    def _connect_notify(self, task_spec):
        """
        Called by the previous task to let us know that it exists.
        """
        raise WorkflowException('StartTask can not have any inputs.', task_spec=self)

    def test(self):
        """
        Checks whether all required attributes are set. Throws an exception
        if an error was detected.
        """
        if len(self.inputs) != 0:
            raise WorkflowException('StartTask with an input.', task_spec=self)
        elif len(self.outputs) < 1:
            raise WorkflowException('No output task connected.', task_spec=self)

    def serialize(self, serializer):
        return serializer.serialize_start_task(self)

    @classmethod
    def deserialize(cls, serializer, wf_spec, s_state):
        return serializer.deserialize_start_task(wf_spec, s_state)

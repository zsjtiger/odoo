# Copyright 2023 The CrossNow.inc Authors.
#

from .base import TaskSpec


class ReleaseMutex(TaskSpec):

    """
    This class implements a task that releases a mutex (lock), protecting
    a section of the workflow from being accessed by other sections.
    If more than one input is connected, the task performs an implicit
    multi merge.
    If more than one output is connected, the task performs an implicit
    parallel split.
    """

    def __init__(self, wf_spec, name, mutex, **kwargs):
        """
        Constructor.

        :type  wf_spec: WorkflowSpec
        :param wf_spec: A reference to the workflow specification.
        :type  name: str
        :param name: The name of the task spec.
        :type  mutex: str
        :param mutex: The name of the mutex that should be released.
        :type  kwargs: dict
        :param kwargs: See :class:`gluon.specs.TaskSpec`.
        """
        assert mutex is not None
        TaskSpec.__init__(self, wf_spec, name, **kwargs)
        self.mutex = mutex

    def _run_hook(self, my_task):
        mutex = my_task.workflow._get_mutex(self.mutex)
        mutex.unlock()
        return True

    def serialize(self, serializer):
        return serializer.serialize_release_mutex(self)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_release_mutex(wf_spec, s_state)

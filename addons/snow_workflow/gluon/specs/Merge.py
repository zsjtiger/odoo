# Copyright 2023 The CrossNow.inc Authors.
#
from .Join import Join
from ..util.deep_merge import DeepMerge


class Merge(Join):

    """Same as Join, but merges all input data instead of just parents'

    Note: data fields that have conflicting names will be overwritten"""

    def _do_join(self, my_task):
        # Merge all inputs (in order)
        for input_spec in self.inputs:
            tasks = [task for task in my_task.workflow.task_tree
                     if task.task_spec is input_spec]
            for task in tasks:
                DeepMerge.merge(my_task.data, task.data)
        return super(Merge, self)._do_join(my_task)

    @classmethod
    def deserialize(self, serializer, wf_spec, s_state):
        return serializer.deserialize_merge(wf_spec, s_state)

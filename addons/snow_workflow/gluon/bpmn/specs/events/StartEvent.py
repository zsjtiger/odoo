# Copyright 2023 The CrossNow.inc Authors.
#

from .event_types import CatchingEvent
from ....task import TaskState


class StartEvent(CatchingEvent):
    """Task Spec for a bpmn:startEvent node with an optional event definition."""

    def __init__(self, wf_spec, name, event_definition, **kwargs):
        super(StartEvent, self).__init__(wf_spec, name, event_definition, **kwargs)

    @property
    def spec_type(self):
        return f'{self.event_definition.event_type} Start Event'

    def catch(self, my_task, event_definition):

        # We might need to revisit a start event after it completes or
        # if it got cancelled so we'll still catch messages even if we're finished
        if my_task.state == TaskState.COMPLETED or my_task.state == TaskState.CANCELLED:
            my_task.set_children_future()
            my_task._set_state(TaskState.WAITING)

        super(StartEvent, self).catch(my_task, event_definition)


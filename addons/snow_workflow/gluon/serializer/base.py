

from .. import operators
from ..specs.AcquireMutex import AcquireMutex
from ..specs.Cancel import Cancel
from ..specs.CancelTask import CancelTask
from ..specs.Choose import Choose
from ..specs.ExclusiveChoice import ExclusiveChoice
from ..specs.Execute import Execute
from ..specs.Gate import Gate
from ..specs.Join import Join
from ..specs.Merge import Merge
from ..specs.MultiChoice import MultiChoice
from ..specs.MultiInstance import MultiInstance
from ..specs.ReleaseMutex import ReleaseMutex
from ..specs.Simple import Simple
from ..specs.StartTask import StartTask
from ..specs.SubWorkflow import SubWorkflow
from ..specs.ThreadStart import ThreadStart
from ..specs.ThreadMerge import ThreadMerge
from ..specs.ThreadSplit import ThreadSplit
from ..specs.Transform import Transform
from ..specs.Trigger import Trigger
from ..specs.WorkflowSpec import WorkflowSpec

# Create a list of tag names out of the spec names.
def spec_map():
    return {
        'acquire-mutex': AcquireMutex,
        'cancel': Cancel,
        'cancel-task': CancelTask,
        'choose': Choose,
        'exclusive-choice': ExclusiveChoice,
        'execute': Execute,
        'gate': Gate,
        'join': Join,
        'merge': Merge,
        'multi-choice': MultiChoice,
        'multi-instance': MultiInstance,
        'release-mutex': ReleaseMutex,
        'simple': Simple,
        'start-task': StartTask,
        'sub-workflow': SubWorkflow,
        'thread-start': ThreadStart,
        'thread-merge': ThreadMerge,
        'thread-split': ThreadSplit,
        'transform': Transform,
        'trigger': Trigger,
        'workflow-spec': WorkflowSpec,
        'task': Simple,
    }

def op_map():
    return {
        'equals':       operators.Equal,
        'not-equals':   operators.NotEqual,
        'less-than':    operators.LessThan,
        'greater-than': operators.GreaterThan,
        'matches':      operators.Match
    }


class Serializer(object):

    def serialize_workflow_spec(self, wf_spec, **kwargs):
        raise NotImplementedError(
            "You must implement the serialize_workflow_spec method.")

    def deserialize_workflow_spec(self, s_state, **kwargs):
        raise NotImplementedError(
            "You must implement the deserialize_workflow_spec method.")

    def serialize_workflow(self, workflow, **kwargs):
        raise NotImplementedError(
            "You must implement the serialize_workflow method.")

    def deserialize_workflow(self, s_state, **kwargs):
        raise NotImplementedError(
            "You must implement the deserialize_workflow method.")

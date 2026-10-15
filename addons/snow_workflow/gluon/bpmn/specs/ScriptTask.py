# Copyright 2023 The CrossNow.inc Authors.
#

from .BpmnSpecMixin import BpmnSpecMixin
from ...specs.Simple import Simple


class ScriptEngineTask(Simple, BpmnSpecMixin):
    """Task Spec for a bpmn:scriptTask node"""

    def _execute(self, task):
        """Please override for specific Implementations, see ScriptTask below for an example"""
        pass

    def _run_hook(self, task):
        return self._execute(task)


class ScriptTask(ScriptEngineTask):

    def __init__(self, wf_spec, name, script, **kwargs):
        """
        Constructor.

        :param script: the script that must be executed by the script engine.
        """
        super(ScriptTask, self).__init__(wf_spec, name, **kwargs)
        self.script = script

    @property
    def spec_type(self):
        return 'Script Task'

    def _execute(self, task):
        return task.workflow.script_engine.execute(task, self.script)

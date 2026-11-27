# Copyright 2023 The CrossNow.inc Authors.
#

from ...spiff.specs.spiff_task import SpiffBpmnTask
from ...bpmn.specs.ScriptTask import ScriptTask as BpmnScriptTask


class ScriptTask(BpmnScriptTask, SpiffBpmnTask):
    pass

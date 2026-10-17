# Copyright 2023 The CrossNow.inc Authors.
#

from ...spiff.specs.spiff_task import SpiffBpmnTask

class NoneTask(SpiffBpmnTask):

    def is_engine_task(self):
        return False

    @property
    def spec_type(self):
        return 'Task'
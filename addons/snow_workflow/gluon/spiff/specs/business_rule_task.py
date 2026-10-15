# Copyright 2023 The CrossNow.inc Authors.
#

from ...spiff.specs.spiff_task import SpiffBpmnTask
from ...dmn.specs.BusinessRuleTask import BusinessRuleTask as DefaultBusinessRuleTask

class BusinessRuleTask(DefaultBusinessRuleTask, SpiffBpmnTask):
    pass

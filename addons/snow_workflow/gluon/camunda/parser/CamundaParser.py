# Copyright 2023 The CrossNow.inc Authors.
#

from ...bpmn.parser.BpmnParser import full_tag, DEFAULT_NSMAP

from ...bpmn.specs.ManualTask import ManualTask
from ...bpmn.specs.NoneTask import NoneTask
from ...bpmn.specs.ScriptTask import ScriptTask
from ...bpmn.specs.SubWorkflowTask import CallActivity, TransactionSubprocess

from ...dmn.parser.BpmnDmnParser import BpmnDmnParser
from ...dmn.specs.BusinessRuleTask import BusinessRuleTask
from ...camunda.specs.UserTask import UserTask
from ...spiff.specs.service_task import ServiceTask as SpiffServiceTask
from ...camunda.parser.task_spec import (
    CamundaTaskParser,
    CamundaServiceTaskParser,
    BusinessRuleTaskParser,
    UserTaskParser,
    CallActivityParser,
    SubWorkflowParser,
    ScriptTaskParser,
    CAMUNDA_MODEL_NS
)

from ...bpmn.specs.events.StartEvent import StartEvent
from ...bpmn.specs.events.EndEvent import EndEvent
from ...bpmn.specs.events.IntermediateEvent import IntermediateThrowEvent, IntermediateCatchEvent, BoundaryEvent
from .event_parsers import (
    CamundaStartEventParser,
    CamundaEndEventParser,
    CamundaIntermediateCatchEventParser,
    CamundaIntermediateThrowEventParser,
    CamundaBoundaryEventParser,
)

NSMAP = DEFAULT_NSMAP.copy()
NSMAP['camunda'] = CAMUNDA_MODEL_NS

class CamundaParser(BpmnDmnParser):

    OVERRIDE_PARSER_CLASSES = {
        full_tag('userTask'): (UserTaskParser, UserTask),
        full_tag('startEvent'): (CamundaStartEventParser, StartEvent),
        full_tag('endEvent'): (CamundaEndEventParser, EndEvent),
        full_tag('intermediateCatchEvent'): (CamundaIntermediateCatchEventParser, IntermediateCatchEvent),
        full_tag('intermediateThrowEvent'): (CamundaIntermediateThrowEventParser, IntermediateThrowEvent),
        full_tag('boundaryEvent'): (CamundaBoundaryEventParser, BoundaryEvent),
        full_tag('businessRuleTask'): (BusinessRuleTaskParser, BusinessRuleTask),
        full_tag('task'): (CamundaTaskParser, NoneTask),
        full_tag('manualTask'): (CamundaTaskParser, ManualTask),
        full_tag('scriptTask'): (ScriptTaskParser, ScriptTask),
        full_tag('serviceTask'): (CamundaServiceTaskParser, SpiffServiceTask),
        full_tag('subProcess'): (SubWorkflowParser, CallActivity),
        full_tag('callActivity'): (CallActivityParser, CallActivity),
        full_tag('transaction'): (SubWorkflowParser, TransactionSubprocess),
    }

    def __init__(self, namespaces=None, validator=None):
        super().__init__(namespaces=namespaces or NSMAP, validator=validator)
# Copyright 2023 The CrossNow.inc Authors.
#

import os

from ...dmn.parser.BpmnDmnParser import BpmnDmnParser
from ...bpmn.parser.BpmnParser import BpmnValidator, full_tag, ValidationException

from ...bpmn.specs.events.EndEvent import EndEvent
from ...bpmn.specs.events.StartEvent import StartEvent
from ...bpmn.specs.events.IntermediateEvent import IntermediateThrowEvent, BoundaryEvent, IntermediateCatchEvent

from ...spiff.specs.none_task import NoneTask
from ...spiff.specs.manual_task import ManualTask
from ...spiff.specs.user_task import UserTask
from ...spiff.specs.script_task import ScriptTask
from ...spiff.specs.subworkflow_task import SubWorkflowTask, TransactionSubprocess, CallActivity
from ...spiff.specs.service_task import ServiceTask
from ...spiff.specs.events.event_types import SendTask, ReceiveTask
from ...spiff.specs.business_rule_task import BusinessRuleTask
from ...spiff.parser.task_spec import (
    SpiffTaskParser,
    SubWorkflowParser,
    CallActivityParser,
    ServiceTaskParser,
    ScriptTaskParser,
    BusinessRuleTaskParser
)
from ...spiff.parser.event_parsers import (SpiffStartEventParser, SpiffEndEventParser, SpiffBoundaryEventParser,
    SpiffIntermediateCatchEventParser, SpiffIntermediateThrowEventParser, SpiffSendTaskParser, SpiffReceiveTaskParser)


from ...spiff.parser.task_spec import BusinessRuleTaskParser

SPIFF_XSD = os.path.join(os.path.dirname(__file__), 'schema', 'gluon.xsd')
VALIDATOR = BpmnValidator(imports={'gluon': SPIFF_XSD})


class SpiffBpmnParser(BpmnDmnParser):

    OVERRIDE_PARSER_CLASSES = {
        full_tag('task'): (SpiffTaskParser, NoneTask),
        full_tag('userTask'): (SpiffTaskParser, UserTask),
        full_tag('manualTask'): (SpiffTaskParser, ManualTask),
        full_tag('scriptTask'): (ScriptTaskParser, ScriptTask),
        full_tag('subProcess'): (SubWorkflowParser, SubWorkflowTask),
        full_tag('transaction'): (SubWorkflowParser, TransactionSubprocess),
        full_tag('callActivity'): (CallActivityParser, CallActivity),
        full_tag('serviceTask'): (ServiceTaskParser, ServiceTask),
        full_tag('startEvent'): (SpiffStartEventParser, StartEvent),
        full_tag('endEvent'): (SpiffEndEventParser, EndEvent),
        full_tag('boundaryEvent'): (SpiffBoundaryEventParser, BoundaryEvent),
        full_tag('intermediateCatchEvent'): (SpiffIntermediateCatchEventParser, IntermediateCatchEvent),
        full_tag('intermediateThrowEvent'): (SpiffIntermediateThrowEventParser, IntermediateThrowEvent),
        full_tag('sendTask'): (SpiffSendTaskParser, SendTask),
        full_tag('receiveTask'): (SpiffReceiveTaskParser, ReceiveTask),
        full_tag('businessRuleTask'): (BusinessRuleTaskParser, BusinessRuleTask)
    }

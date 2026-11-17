# Copyright 2023 The CrossNow.inc Authors.
#

from ...bpmn.serializer.helpers.spec import EventDefinitionConverter
from ..specs.events.event_definitions import MessageEventDefinition


class MessageEventDefinitionConverter(EventDefinitionConverter):

    def __init__(self, registry):
        # 与 bpmn 的 MessageEventDefinition 类名相同, 必须使用独立的 typename, 否则互相覆盖
        super().__init__(MessageEventDefinition, registry, typename='CamundaMessageEventDefinition')

    def to_dict(self, event_definition):
        dct = super().to_dict(event_definition)
        dct['correlation_properties'] = self.correlation_properties_to_dict(event_definition.correlation_properties)
        dct['payload'] = event_definition.payload
        dct['result_var'] = event_definition.result_var
        return dct

    def from_dict(self, dct):
        dct['correlation_properties'] = self.correlation_properties_from_dict(dct['correlation_properties'])
        event_definition = super().from_dict(dct)
        return event_definition

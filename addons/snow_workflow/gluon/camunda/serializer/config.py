# Copyright 2023 The CrossNow.inc Authors.
#

from copy import deepcopy

from ...bpmn.serializer.workflow import DEFAULT_SPEC_CONFIG
from ...bpmn.serializer.task_spec import (
    UserTaskConverter as DefaultUserTaskConverter,
    ParallelMultiInstanceTaskConverter as DefaultParallelMIConverter,
    SequentialMultiInstanceTaskConverter as DefaultSequentialMIConverter,
)
from ...bpmn.serializer.event_definition import MessageEventDefinitionConverter as DefaultMessageEventConverter

from ...spiff.serializer.task_spec import ServiceTaskConverter
from .task_spec import UserTaskConverter, ParallelMultiInstanceTaskConverter, SequentialMultiInstanceTaskConverter
from .event_definition import MessageEventDefinitionConverter


CAMUNDA_SPEC_CONFIG = deepcopy(DEFAULT_SPEC_CONFIG)
CAMUNDA_SPEC_CONFIG['task_specs'].remove(DefaultUserTaskConverter)
CAMUNDA_SPEC_CONFIG['task_specs'].append(UserTaskConverter)
CAMUNDA_SPEC_CONFIG['task_specs'].remove(DefaultParallelMIConverter)
CAMUNDA_SPEC_CONFIG['task_specs'].append(ParallelMultiInstanceTaskConverter)
CAMUNDA_SPEC_CONFIG['task_specs'].remove(DefaultSequentialMIConverter)
CAMUNDA_SPEC_CONFIG['task_specs'].append(SequentialMultiInstanceTaskConverter)

CAMUNDA_SPEC_CONFIG['task_specs'].append(ServiceTaskConverter)

# 解析器创建的消息事件是 bpmn 的 MessageEventDefinition, 默认转换器必须保留;
# camunda 的子类 (如设计器中的消息) 另加转换器, 两者按类区分
CAMUNDA_SPEC_CONFIG['event_definitions'].append(MessageEventDefinitionConverter)

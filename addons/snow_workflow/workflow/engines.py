# -*- coding: utf-8 -*-
import json
import re

from ..gluon.bpmn.workflow import BpmnWorkflow
from ..gluon.camunda.parser.CamundaParser import CamundaParser
from ..gluon.camunda.serializer.config import CAMUNDA_SPEC_CONFIG
from ..gluon.bpmn.serializer.workflow import BpmnWorkflowSerializer
from .service_operations import SnowScriptEngine
from .exceptions import (SnowWorkflowValidationError,
                         SnowWorkflowEngineNoXmlStringError,
                         SnowWorkflowEngineNoJsonStringError)


def _strip_xml_declaration(text):
    """lxml 不接受带编码声明的 unicode 字符串"""
    return re.sub(r'^\s*<\?xml[^>]*\?>', '', text)


class BpmnWorkflowEngine(object):
    """
    Engine的核心功能:

    1. XML -> Workflow Object
    2. Json <--> Workflow Object
    3. Json <--> Task Object
    """

    def __init__(self, xml_str=None, json_str=None, dmn_str=None):
        # 填充xml_str与json_str
        self.xml_str = xml_str
        self.json_str = json_str

        # 配置Camunda引擎规则转换, 配置Serializer
        wf_spec_converter = BpmnWorkflowSerializer.configure_workflow_spec_converter(CAMUNDA_SPEC_CONFIG)
        self.serializer = BpmnWorkflowSerializer(wf_spec_converter)

        # 配置CamundaParser; 业务规则任务需要的 DMN 决策表与流程一起加载
        if self.xml_str is not None:
            self.parser = CamundaParser()
            self.parser.add_bpmn_str(xml_str)
            if dmn_str:
                self.parser.add_dmn_str(_strip_xml_declaration(dmn_str))

    @staticmethod
    def dmn_decision_ids(dmn_str):
        """
        DMN 文本中定义的决策 id; 决策表有错误时抛出异常
        """
        parser = CamundaParser()
        parser.add_dmn_str(_strip_xml_declaration(dmn_str))
        for decision_id in parser.dmn_parsers:
            parser.get_engine(decision_id, None)
        return set(parser.dmn_parsers)

    def _get_workflow_all_specs_from_xml_parser(self):
        """
        获取当前XML中定义的所有工作流描述
        """
        if self.xml_str is None:
            raise SnowWorkflowEngineNoXmlStringError("There is no xml_str object in BpmnWorkflowEngine")

        if 'main_process' not in self.parser.get_process_ids():
            raise SnowWorkflowValidationError("There is no main_process object in XML!")

        return self.parser.find_all_specs()

    def get_workflow_obj_from_xml_parser(self) -> BpmnWorkflow:
        """
        通过process_id获取workflow object
        :return: workflow
        """
        # all_specs = self._get_workflow_all_specs_from_xml_parser()
        if self.xml_str is None:
            raise SnowWorkflowEngineNoXmlStringError("There is no xml_str object in BpmnWorkflowEngine")

        if 'main_process' not in self.parser.get_process_ids():
            raise SnowWorkflowValidationError("There is no main_process object in XML!")

        main_process_spec = self.parser.get_spec('main_process')
        subprocess_specs = self.parser.get_subprocess_specs('main_process')
        return BpmnWorkflow(top_level_spec=main_process_spec, subprocess_specs=subprocess_specs,
                            script_engine=SnowScriptEngine())

    def load_workflow_from_json_str(self):
        """
        将 json字符串 转换为 workflow对象
        """
        if self.json_str is None:
            raise SnowWorkflowEngineNoJsonStringError

        workflow = self.serializer.deserialize_json(json.loads(self.json_str))
        workflow.script_engine = SnowScriptEngine()
        return workflow

    def save_workflow_obj_to_json_str(self, workflow):
        """
        将 workflow对象 转换为 json字符串
        """
        return json.dumps(
            self.serializer.workflow_to_dict(workflow),
            indent=2,
            separators=(',', ':')
        )

    def save_task_obj_to_json_str(self, task):
        """
        将 task对象 转换为 json字符串
        """
        return json.dumps(
            self.serializer.task_to_dict(task),
            indent=2,
            separators=(",", ":")
        )

    def save_task_obj_spec_to_json_str(self, task):
        """
        将 task spec对象 转换为 json字符串
        """
        wf_dct = self.serializer.workflow_to_dict(task.workflow)
        spec_dct = wf_dct['spec']

        return json.dumps(
            spec_dct['task_specs'][task.task_spec.name],
            indent=2,
            separators=(",", ":")
        )


class SnowWorkflowEngine(object):
    """
    后续解析我们自定义的XML
    """
    pass

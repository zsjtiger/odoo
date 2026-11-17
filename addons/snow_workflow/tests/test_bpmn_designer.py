# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..gluon.task import TaskState

from ..workflow.engines import BpmnWorkflowEngine
from ..workflow.service_operations import SnowScriptEngine

# 与设计器 toBpmnXml 生成的格式一致: 一个审批节点 (提交人), 带 lane 与坐标
DESIGNED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_demo" targetNamespace="http://snow.workflow/bpmn">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_task1" name="{'user': 'submitter'}">
        <bpmn:flowNodeRef>task1</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="start1">
      <bpmn:outgoing>flow1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="task1" name="approve_execution">
      <bpmn:incoming>flow1</bpmn:incoming>
      <bpmn:outgoing>flow2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:endEvent id="end1">
      <bpmn:incoming>flow2</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="flow1" sourceRef="start1" targetRef="task1"/>
    <bpmn:sequenceFlow id="flow2" sourceRef="task1" targetRef="end1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="main_process">
      <bpmndi:BPMNShape id="start1_di" bpmnElement="start1"><dc:Bounds x="60" y="120" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="task1_di" bpmnElement="task1"><dc:Bounds x="160" y="98" width="120" height="60"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="end1_di" bpmnElement="end1"><dc:Bounds x="340" y="120" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow1_di" bpmnElement="flow1"><di:waypoint x="96" y="138"/><di:waypoint x="160" y="128"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="flow2_di" bpmnElement="flow2"><di:waypoint x="280" y="128"/><di:waypoint x="340" y="138"/></bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


@tagged('post_install', '-at_install')
class TestBpmnDesigner(TransactionCase):

    def _definition(self, **vals):
        values = {
            'name': 'designer flow',
            'process_id': 'seed',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
            'content': DESIGNED_XML,
        }
        values.update(vals)
        return self.env['snow.workflow.definition'].create(values)

    def test_button_opens_the_designer_client_action(self):
        definition = self._definition()
        action = definition.action_open_designer()
        self.assertEqual(action['tag'], 'snow_workflow_designer')
        self.assertEqual(action['params'], {'definition_id': definition.id})

    def test_save_bpmn_stores_the_designed_diagram(self):
        definition = self._definition()
        changed = DESIGNED_XML.replace('name="approve_execution"', 'name="group_approve_execution_or"')
        definition.save_bpmn(changed)
        self.assertEqual(definition.content, changed)
        self.assertEqual(definition.process_id, 'main_process')

    def test_a_new_definition_starts_with_a_valid_empty_process(self):
        definition = self.env['snow.workflow.definition'].create({
            'name': 'new flow',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
        })
        engine = BpmnWorkflowEngine(xml_str=definition.content)
        self.assertEqual(engine.parser.get_process_ids(), ['main_process'])

    def test_save_bpmn_requires_the_main_process(self):
        definition = self._definition()
        other = DESIGNED_XML.replace('id="main_process"', 'id="other_process"')
        with self.assertRaises(UserError):
            definition.save_bpmn(other)

    def test_save_bpmn_rejects_elements_the_designer_does_not_support(self):
        definition = self._definition()
        exclusive = DESIGNED_XML.replace(
            '<bpmn:endEvent id="end1">',
            '<bpmn:exclusiveGateway id="gw1"/><bpmn:endEvent id="end1">')
        with self.assertRaises(UserError):
            definition.save_bpmn(exclusive)
        service = DESIGNED_XML.replace(
            '<bpmn:endEvent id="end1">',
            '<bpmn:serviceTask id="svc1" name="call"/><bpmn:endEvent id="end1">')
        with self.assertRaises(UserError):
            definition.save_bpmn(service)

    def test_save_bpmn_rejects_nodes_without_flows(self):
        definition = self._definition()
        orphan = DESIGNED_XML.replace(
            '<bpmn:endEvent id="end1">',
            '<bpmn:userTask id="lonely" name="approve_execution"/><bpmn:endEvent id="end1">')
        with self.assertRaises(UserError):
            definition.save_bpmn(orphan)

    def test_save_bpmn_rejects_content_that_is_not_bpmn(self):
        definition = self._definition()
        with self.assertRaises(UserError):
            definition.save_bpmn('<not-bpmn/>')
        with self.assertRaises(UserError):
            definition.save_bpmn('plain text, not xml')
        # 原内容不变
        self.assertEqual(definition.content, DESIGNED_XML)

    def test_the_designed_process_builds_a_runnable_workflow(self):
        engine = BpmnWorkflowEngine(xml_str=DESIGNED_XML)
        workflow = engine.get_workflow_obj_from_xml_parser()
        self.assertIsNotNone(workflow)
        spec = engine.parser.get_spec('main_process')
        self.assertEqual(spec.task_specs['task1'].lane, "{'user': 'submitter'}")

    def test_the_engine_reads_the_approver_lane_of_the_task(self):
        engine = BpmnWorkflowEngine(xml_str=DESIGNED_XML)
        parser_spec = engine.parser.get_process_ids()
        self.assertEqual(parser_spec, ['main_process'])
        specs = engine._get_workflow_all_specs_from_xml_parser()
        self.assertTrue(specs)


GATEWAY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:startEvent id="s1"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="s1" targetRef="gw"/>
    <bpmn:exclusiveGateway id="gw" default="f_no">
      <bpmn:incoming>f0</bpmn:incoming><bpmn:outgoing>f_yes</bpmn:outgoing><bpmn:outgoing>f_no</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:sequenceFlow id="f_yes" sourceRef="gw" targetRef="e1">
      <bpmn:conditionExpression>amount &gt; 100</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="f_no" sourceRef="gw" targetRef="e2"/>
    <bpmn:endEvent id="e1"><bpmn:incoming>f_yes</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="e2"><bpmn:incoming>f_no</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""

SERVICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:startEvent id="s1"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="s1" targetRef="svc"/>
    <bpmn:serviceTask id="svc" name="Compute">
      <bpmn:extensionElements><camunda:properties>
        <camunda:property name="serviceTaskOperator"
          value="{&quot;name&quot;: &quot;evaluate&quot;, &quot;parameters&quot;: {&quot;value&quot;: {&quot;value&quot;: &quot;amount * 2&quot;}}, &quot;resultVariable&quot;: &quot;total&quot;}"/>
      </camunda:properties></bpmn:extensionElements>
      <bpmn:incoming>f0</bpmn:incoming><bpmn:outgoing>f1</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="f1" sourceRef="svc" targetRef="e1"/>
    <bpmn:endEvent id="e1"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""

SUBPROCESS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:startEvent id="s1"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="s1" targetRef="sub"/>
    <bpmn:subProcess id="sub" name="Inner">
      <bpmn:incoming>f0</bpmn:incoming><bpmn:outgoing>f1</bpmn:outgoing>
      <bpmn:startEvent id="ss"><bpmn:outgoing>sf</bpmn:outgoing></bpmn:startEvent>
      <bpmn:sequenceFlow id="sf" sourceRef="ss" targetRef="se"/>
      <bpmn:endEvent id="se"><bpmn:incoming>sf</bpmn:incoming></bpmn:endEvent>
    </bpmn:subProcess>
    <bpmn:sequenceFlow id="f1" sourceRef="sub" targetRef="e1"/>
    <bpmn:endEvent id="e1"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


@tagged('post_install', '-at_install')
class TestDesignerConstructs(TransactionCase):

    def _definition(self):
        return self.env['snow.workflow.definition'].create({
            'name': 'constructs',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
        })

    def test_gateway_with_conditions_is_saved(self):
        self._definition().save_bpmn(GATEWAY_XML)

    def test_a_condition_that_is_not_python_is_rejected(self):
        broken = GATEWAY_XML.replace('amount &gt; 100', 'amount &gt;')
        with self.assertRaises(UserError):
            self._definition().save_bpmn(broken)

    def test_a_gateway_without_default_flow_is_rejected(self):
        no_default = GATEWAY_XML.replace(' default="f_no"', '')
        with self.assertRaises(UserError):
            self._definition().save_bpmn(no_default)

    def test_a_service_task_needs_a_registered_operation(self):
        unknown = SERVICE_XML.replace('&quot;evaluate&quot;', '&quot;delete_everything&quot;')
        with self.assertRaises(UserError):
            self._definition().save_bpmn(unknown)

    def test_a_service_task_with_a_valid_operation_is_saved(self):
        self._definition().save_bpmn(SERVICE_XML)

    def test_a_subprocess_is_saved(self):
        self._definition().save_bpmn(SUBPROCESS_XML)

    def test_a_subprocess_is_checked_like_a_process(self):
        orphan = SUBPROCESS_XML.replace(
            '<bpmn:sequenceFlow id="sf" sourceRef="ss" targetRef="se"/>', '')
        with self.assertRaises(UserError):
            self._definition().save_bpmn(orphan)

    @staticmethod
    def _workflow(xml, **data):
        # 与 snow_workflow 的启动方式一致: 数据写入每个任务
        workflow = BpmnWorkflowEngine(xml_str=xml).get_workflow_obj_from_xml_parser()
        for task in workflow.get_tasks():
            task.set_data(**data)
        return workflow

    def _finished_ends(self, xml, **data):
        workflow = self._workflow(xml, **data)
        workflow.do_engine_steps()
        return sorted(t.task_spec.name for t in workflow.get_tasks()
                      if t.task_spec.name.startswith('e') and t.state == TaskState.COMPLETED)

    def test_the_engine_routes_by_the_gateway_condition(self):
        engine = BpmnWorkflowEngine(xml_str=GATEWAY_XML)
        self.assertEqual(self._finished_ends(GATEWAY_XML, amount=200), ['e1'])
        self.assertEqual(self._finished_ends(GATEWAY_XML, amount=50), ['e2'])

    def test_the_service_task_runs_its_operation(self):
        workflow = self._workflow(SERVICE_XML, amount=21)
        workflow.do_engine_steps()
        self.assertTrue(workflow.is_completed())
        self.assertEqual(workflow.data.get('total'), 42)

    def test_the_subprocess_completes(self):
        engine = BpmnWorkflowEngine(xml_str=SUBPROCESS_XML)
        workflow = engine.get_workflow_obj_from_xml_parser()
        for _ in range(5):
            workflow.do_engine_steps()
            workflow.refresh_waiting_tasks()
        self.assertTrue(workflow.is_completed())

    def test_a_workflow_with_a_service_task_survives_save_and_reload(self):
        workflow = self._workflow(SERVICE_XML, amount=21)
        workflow.do_engine_steps()
        json_str = BpmnWorkflowEngine().save_workflow_obj_to_json_str(workflow)
        reloaded = BpmnWorkflowEngine(json_str=json_str).load_workflow_from_json_str()
        self.assertIsInstance(reloaded.script_engine, SnowScriptEngine)
        self.assertTrue(reloaded.is_completed())
        self.assertEqual(reloaded.data.get('total'), 42)

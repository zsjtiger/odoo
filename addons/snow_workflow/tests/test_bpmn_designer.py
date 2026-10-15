# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..workflow.engines import BpmnWorkflowEngine

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

# -*- coding: utf-8 -*-
import time

from odoo.tests import TransactionCase, tagged

from ..gluon.task import TaskState
from ..gluon.bpmn.specs.events.event_definitions import MessageEventDefinition
from ..workflow.engines import BpmnWorkflowEngine
from ..workflow.snow_workflow import SnowWorkflow


def _definitions(body):
    return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:camunda="http://camunda.org/schema/1.0/bpmn" id="Definitions_t" targetNamespace="http://snow.workflow/bpmn">
  <bpmn:message id="m" name="m"/>
  <bpmn:process id="main_process" isExecutable="true">%s</bpmn:process>
</bpmn:definitions>
""" % body


def _linear(middle):
    """start -> middle -> end, 中间节点的 id 为 t"""
    return ('<bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>' + middle +
            '<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
            '<bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>')


def _timer_process(duration, approver_id):
    """定时器之后是一个审批节点, 审批人为指定用户 (不是提交人, 避免被当作自审批)"""
    lane = "{'user': {'domain': [('id', '=', %d)]}}" % approver_id
    return ('<bpmn:laneSet id="LaneSet_1"><bpmn:lane id="Lane_approve" name="%s">'
            '<bpmn:flowNodeRef>approve</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>'
            '<bpmn:startEvent id="start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="wait"/>'
            '<bpmn:intermediateCatchEvent id="wait"><bpmn:incoming>f1</bpmn:incoming>'
            '<bpmn:outgoing>f2</bpmn:outgoing><bpmn:timerEventDefinition>'
            '<bpmn:timeDuration>\'%s\'</bpmn:timeDuration></bpmn:timerEventDefinition>'
            '</bpmn:intermediateCatchEvent>'
            '<bpmn:sequenceFlow id="f2" sourceRef="wait" targetRef="approve"/>'
            '<bpmn:userTask id="approve" name="approve_execution"><bpmn:incoming>f2</bpmn:incoming>'
            '<bpmn:outgoing>f3</bpmn:outgoing></bpmn:userTask>'
            '<bpmn:sequenceFlow id="f3" sourceRef="approve" targetRef="end"/>'
            '<bpmn:endEvent id="end"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>') % (lane, duration)


@tagged('post_install', '-at_install')
class TestTimerAdvance(TransactionCase):

    def setUp(self):
        super().setUp()
        self.approver = self.env['res.users'].create({
            'name': 'timer approver', 'login': 'timer_approver',
        })

    def _submit(self, duration):
        partner = self.env['res.partner'].create({'name': 'timer partner'})
        self.env['snow.workflow.definition'].create({
            'name': 'timer flow',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
            'content': _definitions(_timer_process(duration, self.approver.id)),
        })
        SnowWorkflow(self.env, self.env['snow.workflow.instance']).do_submit(
            instance=False, model='res.partner', record=partner.id)
        return self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', partner.id)], limit=1)

    def _execution_and_active(self, instance):
        execution = instance.wf_executions.filtered(lambda r: not r.is_complete)
        return execution, execution.wf_execution_tasks.filtered('in_progress')

    def test_the_approval_behind_a_timer_is_not_active_at_submit(self):
        instance = self._submit('PT1H')
        execution, active = self._execution_and_active(instance)
        self.assertTrue(execution, 'the process is still running behind the timer')
        self.assertFalse(active)

    def test_a_due_timer_activates_the_next_approval(self):
        instance = self._submit('PT1S')
        _execution, active = self._execution_and_active(instance)
        self.assertFalse(active, 'the timer has not run out at submit time')

        time.sleep(1.2)
        self.env['snow.workflow.execution']._cron_advance_timers()

        execution, active = self._execution_and_active(instance)
        self.assertEqual(len(active), 1)
        self.assertEqual(active.task_attendee.user, self.approver)
        self.assertFalse(execution.is_complete)

    def test_a_timer_that_has_already_expired_at_submit_goes_straight_to_approval(self):
        instance = self._submit('PT0S')
        execution, active = self._execution_and_active(instance)
        self.assertEqual(len(active), 1)
        self.assertFalse(execution.is_complete)

    def test_approving_the_activated_task_completes_the_process(self):
        instance = self._submit('PT1S')
        time.sleep(1.2)
        self.env['snow.workflow.execution']._cron_advance_timers()

        _execution, active = self._execution_and_active(instance)
        SnowWorkflow(self.env, instance).do_single_pass(
            instance=instance.id, task_name=active.task_xml_id, user=self.approver)

        instance.invalidate_recordset()
        self.assertTrue(instance.is_complete)

    def test_a_timer_that_is_not_due_keeps_the_process_waiting(self):
        instance = self._submit('PT1H')
        self.env['snow.workflow.execution']._cron_advance_timers()

        _execution, active = self._execution_and_active(instance)
        self.assertFalse(active)

    def test_a_suspended_instance_does_not_advance(self):
        instance = self._submit('PT1S')
        self.env['snow.workflow.instance.suspend'].create({
            'wf_instance': instance.id,
            'suspend_user': self.env.uid,
        })

        time.sleep(1.2)
        self.env['snow.workflow.execution']._cron_advance_timers()

        _execution, active = self._execution_and_active(instance)
        self.assertFalse(active)


@tagged('post_install', '-at_install')
class TestEngineTaskTypes(TransactionCase):
    """引擎层的任务类型: 按行为断言, 而不是只看能否推进"""

    def _workflow(self, body):
        return BpmnWorkflowEngine(xml_str=_definitions(body)).get_workflow_obj_from_xml_parser()

    def _ready(self, workflow):
        return [t for t in workflow.get_tasks() if t.state == TaskState.READY]

    def _complete_one_by_one(self, workflow):
        iterations = 0
        while self._ready(workflow) and iterations < 10:
            self._ready(workflow)[0].run()
            workflow.do_engine_steps()
            iterations += 1
        return iterations

    def test_sequential_multi_instance_runs_one_iteration_after_another(self):
        workflow = self._workflow(_linear(
            '<bpmn:userTask id="t" name="t"><bpmn:multiInstanceLoopCharacteristics isSequential="true">'
            '<bpmn:loopCardinality>2</bpmn:loopCardinality></bpmn:multiInstanceLoopCharacteristics></bpmn:userTask>'))
        workflow.do_engine_steps()
        self.assertEqual(len(self._ready(workflow)), 1)
        self.assertEqual(self._complete_one_by_one(workflow), 2)
        self.assertTrue(workflow.is_completed())

    def test_parallel_multi_instance_is_ready_at_once(self):
        workflow = self._workflow(_linear(
            '<bpmn:userTask id="t" name="t"><bpmn:multiInstanceLoopCharacteristics isSequential="false">'
            '<bpmn:loopCardinality>2</bpmn:loopCardinality></bpmn:multiInstanceLoopCharacteristics></bpmn:userTask>'))
        workflow.do_engine_steps()
        self.assertEqual(len(self._ready(workflow)), 2)
        for task in self._ready(workflow):
            task.run()
        workflow.do_engine_steps()
        self.assertTrue(workflow.is_completed())

    def test_standard_loop_repeats_up_to_the_maximum(self):
        workflow = self._workflow(_linear(
            '<bpmn:userTask id="t" name="t"><bpmn:standardLoopCharacteristics loopMaximum="3"/></bpmn:userTask>'))
        workflow.do_engine_steps()
        self.assertEqual(self._complete_one_by_one(workflow), 3)
        self.assertTrue(workflow.is_completed())

    def test_send_task_completes_and_emits_its_message(self):
        workflow = self._workflow(_linear(
            '<bpmn:sendTask id="t" name="t"><bpmn:messageEventDefinition messageRef="m"/></bpmn:sendTask>'))
        workflow.do_engine_steps()
        self.assertTrue(workflow.is_completed())
        self.assertEqual([message.name for message in workflow.get_bpmn_messages()], ['m'])

    def test_receive_task_waits_until_its_message_arrives(self):
        workflow = self._workflow(_linear('<bpmn:receiveTask id="t" name="t" messageRef="m"/>'))
        workflow.do_engine_steps()
        self.assertFalse(workflow.is_completed())
        self.assertTrue([t for t in workflow.get_tasks()
                         if t.task_spec.name == 't' and t.state == TaskState.WAITING])
        workflow.catch(MessageEventDefinition('m'))
        workflow.do_engine_steps()
        self.assertTrue(workflow.is_completed())

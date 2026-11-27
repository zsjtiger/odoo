# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..workflow.snow_workflow import SnowWorkflow


def _single_approval(approver_id):
    """start -> 一个审批节点 (审批人为指定用户) -> end"""
    lane = "{'user': {'domain': [('id', '=', %d)]}}" % approver_id
    return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:camunda="http://camunda.org/schema/1.0/bpmn" id="Definitions_a" targetNamespace="http://snow.workflow/bpmn">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:laneSet id="LaneSet_1"><bpmn:lane id="Lane_approve" name="%s">
      <bpmn:flowNodeRef>approve</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>
    <bpmn:startEvent id="start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="approve"/>
    <bpmn:userTask id="approve" name="approve_execution"><bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing></bpmn:userTask>
    <bpmn:sequenceFlow id="f2" sourceRef="approve" targetRef="end"/>
    <bpmn:endEvent id="end"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
""" % lane


@tagged('post_install', '-at_install')
class TestApprovalActions(TransactionCase):

    def setUp(self):
        super().setUp()
        self.approver = self.env['res.users'].create({'name': 'approver', 'login': 'approver_a'})
        self.stranger = self.env['res.users'].create({'name': 'stranger', 'login': 'stranger_b'})
        self.partner = self.env['res.partner'].create({'name': 'approval partner'})
        self.env['snow.workflow.definition'].create({
            'name': 'approval flow',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
            'content': _single_approval(self.approver.id),
        })
        # 提交人为测试用户本人, 与审批人不同
        SnowWorkflow(self.env, self.env['snow.workflow.instance']).do_submit(
            instance=False, model='res.partner', record=self.partner.id)
        self.instance = self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', self.partner.id)], limit=1)
        self.task_name = self._active_task().task_xml_id

    def _active_task(self):
        execution = self.instance.wf_executions.filtered(lambda r: not r.is_complete)
        return execution.wf_execution_tasks.filtered('in_progress')

    def _act(self, user, trigger, **kwargs):
        """模拟前端按钮的调用: 参数由前端回传"""
        value = {
            'trigger_function': trigger,
            'kwargs': kwargs,
            'model_name': 'res.partner',
            'record_id': self.partner.id,
        }
        return self.env['snow.workflow.action'].with_user(user).approval_action(value)

    def _pass_args(self):
        return {'instance': self.instance.id, 'task_name': self.task_name}

    def test_a_user_who_is_not_the_approver_cannot_pass(self):
        with self.assertRaises(UserError):
            self._act(self.stranger, 'do_single_pass', **self._pass_args())
        self.instance.invalidate_recordset()
        self.assertFalse(self.instance.is_complete)
        self.assertTrue(self._active_task())

    def test_the_approver_passes_and_the_process_completes(self):
        self._act(self.approver, 'do_single_pass', **self._pass_args())
        self.instance.invalidate_recordset()
        self.assertTrue(self.instance.is_complete)

    def test_a_handled_task_cannot_be_approved_again(self):
        self._act(self.approver, 'do_single_pass', **self._pass_args())
        with self.assertRaises(UserError):
            self._act(self.approver, 'do_single_pass', **self._pass_args())

    def test_the_task_name_sent_by_the_client_is_checked(self):
        with self.assertRaises(UserError):
            self._act(self.approver, 'do_single_pass', instance=self.instance.id, task_name='not_a_task')
        self.instance.invalidate_recordset()
        self.assertFalse(self.instance.is_complete)

    def test_an_action_that_is_not_offered_is_rejected(self):
        with self.assertRaises(UserError):
            self._act(self.approver, 'do_suspend_everything', **self._pass_args())

    def test_only_the_initiator_can_withdraw(self):
        with self.assertRaises(UserError):
            self._act(self.approver, 'do_withdraw', **self._pass_args())
        # 测试用户即提交人
        self._act(self.env.user, 'do_withdraw', **self._pass_args())

    def test_the_approver_can_reject(self):
        self._act(self.approver, 'do_single_reject', **self._pass_args())
        self.instance.invalidate_recordset()
        # 拒绝结束本次执行, 但实例只有通过时才完成, 提交人可以修改后重新提交
        self.assertTrue(self.instance.wf_executions[-1].is_complete)
        self.assertFalse(self.instance.is_complete)
        self.assertNotEqual(self.instance.status, 'pass')

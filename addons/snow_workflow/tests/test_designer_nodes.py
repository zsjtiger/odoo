# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..workflow.snow_workflow import SnowWorkflow

DMN = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="defs" name="defs" namespace="x">
<decision id="grade" name="grade"><decisionTable id="dt1" hitPolicy="FIRST">
<input id="i1" label="x"><inputExpression typeRef="integer"><text>x</text></inputExpression></input>
<output id="o1" label="y" name="y" typeRef="string"/>
<rule id="r1"><inputEntry id="ie1"><text>&gt; 5</text></inputEntry><outputEntry id="oe1"><text>"big"</text></outputEntry></rule>
<rule id="r2"><inputEntry id="ie2"><text></text></inputEntry><outputEntry id="oe2"><text>"small"</text></outputEntry></rule>
</decisionTable></decision></definitions>"""


def _process(body, messages=''):
    return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:camunda="http://camunda.org/schema/1.0/bpmn" id="Definitions_n" targetNamespace="http://snow.workflow/bpmn">
  %s
  <bpmn:process id="main_process" isExecutable="true">%s</bpmn:process>
</bpmn:definitions>
""" % (messages, body)


def _linear(middle):
    return ('<bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>' + middle +
            '<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
            '<bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>')


def _service(parameters):
    import json
    operator = json.dumps({'name': 'write_record', 'parameters': parameters, 'resultVariable': None})
    return ('<bpmn:serviceTask id="t" name="t"><bpmn:extensionElements><camunda:properties>'
            '<camunda:property name="serviceTaskOperator" value=\'%s\'/></camunda:properties>'
            '</bpmn:extensionElements></bpmn:serviceTask>') % operator.replace("'", '&apos;')


@tagged('post_install', '-at_install')
class TestDesignerNodes(TransactionCase):

    def setUp(self):
        super().setUp()
        self.definition = self.env['snow.workflow.definition'].create({
            'name': 'nodes',
            'object_id': self.env.ref('base.model_res_partner').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.partner'), ('type', '=', 'form')], limit=1).id,
        })

    def _save(self, body, messages='', dmn=None):
        if dmn is not None:
            self.definition.dmn_content = dmn
        self.definition.save_bpmn(_process(body, messages))

    # 写入业务字段的限制
    def test_write_record_accepts_an_ordinary_field(self):
        self._save(_linear(_service({'name': {'value': "'Demo'"}})))

    def test_write_record_rejects_system_and_unknown_fields(self):
        with self.assertRaises(UserError):
            self._save(_linear(_service({'create_uid': {'value': '1'}})))
        with self.assertRaises(UserError):
            self._save(_linear(_service({'no_such_field': {'value': "'x'"}})))

    def test_write_record_at_runtime_checks_the_field_too(self):
        from ..workflow.service_operations import SERVICE_OPERATIONS
        partner = self.env['res.partner'].create({'name': 'before'})
        task_data = {'script_env': self.env, 'model': 'res.partner', 'record': partner.id}
        SERVICE_OPERATIONS['write_record']({'name': {'value': 'after'}}, task_data)
        self.assertEqual(partner.name, 'after')
        with self.assertRaises(UserError):
            SERVICE_OPERATIONS['write_record']({'id': {'value': 99}}, task_data)

    # 脚本任务: 只有系统管理员可以编辑
    def test_a_script_task_needs_a_system_administrator(self):
        script = ('<bpmn:scriptTask id="t" name="t"><bpmn:script>x = 1</bpmn:script></bpmn:scriptTask>')
        plain = self.env['res.users'].create({'name': 'plain', 'login': 'plain_user',
                                              'group_ids': [(6, 0, [])]})
        with self.assertRaises(UserError):
            self.definition.with_user(plain).save_bpmn(_process(_linear(script)))
        self.definition.save_bpmn(_process(_linear(script)))

    def test_a_script_with_a_syntax_error_is_rejected(self):
        bad = '<bpmn:scriptTask id="t" name="t"><bpmn:script>x = (</bpmn:script></bpmn:scriptTask>'
        with self.assertRaises(UserError):
            self._save(_linear(bad))

    # DMN 与业务规则任务
    def test_a_business_rule_task_uses_a_decision_of_the_dmn(self):
        rule = ('<bpmn:businessRuleTask id="t" name="t" camunda:decisionRef="grade" '
                'camunda:resultVariable="y"/>')
        self._save(_linear(rule), dmn=DMN)

    def test_a_business_rule_task_needs_a_known_decision(self):
        rule = ('<bpmn:businessRuleTask id="t" name="t" camunda:decisionRef="missing" '
                'camunda:resultVariable="y"/>')
        with self.assertRaises(UserError):
            self._save(_linear(rule), dmn=DMN)

    def test_invalid_dmn_is_rejected_when_saved(self):
        with self.assertRaises(ValidationError):
            self.definition.dmn_content = '<definitions><decision id="x"></definitions>'

    # 定时器
    def test_a_timer_needs_a_quoted_iso_duration(self):
        def timer(text):
            return ('<bpmn:intermediateCatchEvent id="t" name="t"><bpmn:timerEventDefinition>'
                    '<bpmn:timeDuration>%s</bpmn:timeDuration></bpmn:timerEventDefinition>'
                    '</bpmn:intermediateCatchEvent>') % text
        self._save(_linear(timer("'PT1H'")))
        self._save(_linear(timer("'P1DT2H'")))
        for bad in ("PT1H", "'1 hour'", "'PT'", "'P'"):
            with self.assertRaises(UserError):
                self._save(_linear(timer(bad)))

    # 消息
    MESSAGE = '<bpmn:message id="Message_go" name="go"/>'

    def test_a_send_and_a_receive_task_use_a_defined_message(self):
        send = ('<bpmn:sendTask id="t" name="t" messageRef="Message_go"/>')
        receive = ('<bpmn:receiveTask id="t" name="t" messageRef="Message_go"/>')
        self._save(_linear(send), messages=self.MESSAGE)
        self._save(_linear(receive), messages=self.MESSAGE)

    def test_a_message_task_without_a_defined_message_is_rejected(self):
        receive = '<bpmn:receiveTask id="t" name="t" messageRef="Message_missing"/>'
        with self.assertRaises(UserError):
            self._save(_linear(receive), messages=self.MESSAGE)

    # 多实例: 只用于自动任务
    MULTI = ('<bpmn:multiInstanceLoopCharacteristics isSequential="%s">'
             '<bpmn:loopCardinality>%s</bpmn:loopCardinality></bpmn:multiInstanceLoopCharacteristics>')

    def test_multi_instance_is_allowed_on_a_script_task(self):
        script = ('<bpmn:scriptTask id="t" name="t"><bpmn:script>x = 1</bpmn:script>%s</bpmn:scriptTask>'
                  % (self.MULTI % ('true', "'2'")))
        self._save(_linear(script))

    def test_multi_instance_is_not_allowed_on_an_approval(self):
        approval = ('<bpmn:userTask id="t" name="approve_execution">%s</bpmn:userTask>'
                    % (self.MULTI % ('true', "'2'")))
        with self.assertRaises(UserError):
            self._save(_linear(approval))

    # 接收消息: 外部投递到同一业务记录的运行中流程
    def test_a_received_message_activates_the_approval_behind_the_receive(self):
        approver = self.env['res.users'].create({'name': 'approver', 'login': 'approver_msg'})
        receive = ('<bpmn:receiveTask id="t" name="t" messageRef="Message_go"/>')
        approval = ('<bpmn:laneSet id="L"><bpmn:lane id="La" name="{\'user\': {\'domain\': [(\'id\', \'=\', %d)]}}">'
                    '<bpmn:flowNodeRef>approve</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>'
                    '<bpmn:startEvent id="s0"><bpmn:outgoing>g0</bpmn:outgoing></bpmn:startEvent>'
                    '<bpmn:sequenceFlow id="g0" sourceRef="s0" targetRef="wait"/>'
                    '<bpmn:receiveTask id="wait" name="wait" messageRef="Message_go">'
                    '<bpmn:outgoing>g1</bpmn:outgoing></bpmn:receiveTask>'
                    '<bpmn:sequenceFlow id="g1" sourceRef="wait" targetRef="approve"/>'
                    '<bpmn:userTask id="approve" name="approve_execution"><bpmn:outgoing>g2</bpmn:outgoing>'
                    '</bpmn:userTask>'
                    '<bpmn:sequenceFlow id="g2" sourceRef="approve" targetRef="end"/>'
                    '<bpmn:endEvent id="end"><bpmn:incoming>g2</bpmn:incoming></bpmn:endEvent>') % approver.id
        self.definition.save_bpmn(_process(approval, messages=self.MESSAGE))
        partner = self.env['res.partner'].create({'name': 'msg partner'})
        SnowWorkflow(self.env, self.env['snow.workflow.instance']).do_submit(
            instance=False, model='res.partner', record=partner.id)
        instance = self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', partner.id)], limit=1)

        def active():
            execution = instance.wf_executions.filtered(lambda r: not r.is_complete)
            return execution.wf_execution_tasks.filtered('in_progress')

        self.assertFalse(active())
        with self.assertRaises(UserError):
            self.env['snow.workflow.action'].receive_message('res.partner', partner.id, 'other')
        self.env['snow.workflow.action'].receive_message('res.partner', partner.id, 'go', {'x': 1})
        self.assertEqual(len(active()), 1)
        self.assertEqual(active().task_attendee.user, approver)

    def test_a_message_for_a_record_without_a_process_is_rejected(self):
        partner = self.env['res.partner'].create({'name': 'no process'})
        with self.assertRaises(UserError):
            self.env['snow.workflow.action'].receive_message('res.partner', partner.id, 'go')

    def test_a_node_other_than_a_gateway_can_have_only_one_outgoing_flow(self):
        script = '<bpmn:scriptTask id="t" name="t"><bpmn:script>x = 1</bpmn:script></bpmn:scriptTask>'
        branched = ('<bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
                    '<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>' + script +
                    '<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
                    '<bpmn:sequenceFlow id="f3" sourceRef="t" targetRef="e2"/>'
                    '<bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
                    '<bpmn:endEvent id="e2"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>')
        with self.assertRaises(UserError):
            self._save(branched)

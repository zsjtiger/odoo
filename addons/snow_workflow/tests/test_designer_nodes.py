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

    def test_a_decision_expression_must_be_valid_python(self):
        # 输入条目的比较 ("> 5") 与输出条目的字符串是合法的
        self.definition.dmn_content = DMN
        broken_input = DMN.replace('<text>x</text>', '<text>x +</text>')
        with self.assertRaises(ValidationError):
            self.definition.dmn_content = broken_input
        broken_output = DMN.replace('<text>"big"</text>', '<text>"big</text>')
        with self.assertRaises(ValidationError):
            self.definition.dmn_content = broken_output

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

    # 跨记录消息: 发送任务带目标记录, 投递给同模型目标记录上正在等待该消息的流程
    def _send_to_then_wait(self, approver, target_id):
        return ('<bpmn:laneSet id="L"><bpmn:lane id="La" name="{\'user\': {\'domain\': [(\'id\', \'=\', %d)]}}">'
                '<bpmn:flowNodeRef>approve</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>'
                '<bpmn:startEvent id="s0"><bpmn:outgoing>g0</bpmn:outgoing></bpmn:startEvent>'
                '<bpmn:sequenceFlow id="g0" sourceRef="s0" targetRef="send"/>'
                '<bpmn:sendTask id="send" name="send" messageRef="Message_go">'
                '<bpmn:extensionElements><camunda:properties>'
                '<camunda:property name="targetRecord" value="%d"/>'
                '</camunda:properties></bpmn:extensionElements><bpmn:outgoing>g1</bpmn:outgoing></bpmn:sendTask>'
                '<bpmn:sequenceFlow id="g1" sourceRef="send" targetRef="wait"/>'
                '<bpmn:receiveTask id="wait" name="wait" messageRef="Message_go"><bpmn:outgoing>g2</bpmn:outgoing>'
                '</bpmn:receiveTask>'
                '<bpmn:sequenceFlow id="g2" sourceRef="wait" targetRef="approve"/>'
                '<bpmn:userTask id="approve" name="approve_execution"><bpmn:outgoing>g3</bpmn:outgoing></bpmn:userTask>'
                '<bpmn:sequenceFlow id="g3" sourceRef="approve" targetRef="end"/>'
                '<bpmn:endEvent id="end"><bpmn:incoming>g3</bpmn:incoming></bpmn:endEvent>') % (approver.id, target_id)

    def _submit(self, partner):
        SnowWorkflow(self.env, self.env['snow.workflow.instance']).do_submit(
            instance=False, model='res.partner', record=partner.id)

    def _active_tasks(self, partner):
        instance = self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', partner.id)], limit=1)
        execution = instance.wf_executions.filtered(lambda r: not r.is_complete)
        return execution.wf_execution_tasks.filtered('in_progress')

    def test_a_cross_record_message_reaches_the_record_waiting_for_it(self):
        approver = self.env['res.users'].create({'name': 'approver', 'login': 'approver_cross'})
        receiver = self.env['res.partner'].create({'name': 'receiver'})
        sender = self.env['res.partner'].create({'name': 'sender'})
        self.definition.save_bpmn(_process(self._send_to_then_wait(approver, receiver.id), messages=self.MESSAGE))
        # 接收方先提交: 它发给自己的消息没有等待者 (不投递给自己), 然后等待消息
        self._submit(receiver)
        self.assertFalse(self._active_tasks(receiver))
        # 发送方提交: 消息投递给接收方, 接收方的审批被激活
        self._submit(sender)
        self.assertEqual(len(self._active_tasks(receiver)), 1)
        self.assertEqual(self._active_tasks(receiver).task_attendee.user, approver)
        self.assertFalse(self._active_tasks(sender))

    def test_a_cross_record_message_is_dropped_when_no_process_waits_for_it(self):
        approver = self.env['res.users'].create({'name': 'approver', 'login': 'approver_drop'})
        nobody = self.env['res.partner'].create({'name': 'nobody'})
        sender = self.env['res.partner'].create({'name': 'sender drop'})
        self.definition.save_bpmn(_process(self._send_to_then_wait(approver, nobody.id), messages=self.MESSAGE))
        self._submit(sender)
        # 目标没有运行中的流程: 消息被丢弃, 发送方照常等待自己的消息
        self.assertFalse(self._active_tasks(sender))
        self.assertTrue(self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', sender.id), ('is_complete', '=', False)]))

    def test_data_objects_are_rejected_because_nothing_runs_them(self):
        script = '<bpmn:scriptTask id="t" name="t"><bpmn:script>x = 1</bpmn:script></bpmn:scriptTask>'
        data = '<bpmn:dataObjectReference id="d" dataObjectRef="o" name="doc"/><bpmn:dataObject id="o"/>'
        with self.assertRaises(UserError):
            self._save(_linear(script) + data)

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

    # 包容网关: 满足的条件都执行; 默认分支只在没有任何条件满足时执行
    INCLUSIVE = ('<bpmn:scriptTask id="pre" name="pre"><bpmn:script>x = %s</bpmn:script></bpmn:scriptTask>'
                 '<bpmn:sequenceFlow id="p" sourceRef="pre" targetRef="g"/>'
                 '<bpmn:inclusiveGateway id="g" name="g" default="fd">'
                 '<bpmn:outgoing>c1</bpmn:outgoing><bpmn:outgoing>fd</bpmn:outgoing></bpmn:inclusiveGateway>'
                 '<bpmn:sequenceFlow id="c1" sourceRef="g" targetRef="e1">'
                 '<bpmn:conditionExpression>x &gt; 5</bpmn:conditionExpression></bpmn:sequenceFlow>'
                 '<bpmn:sequenceFlow id="fd" sourceRef="g" targetRef="e2"/>'
                 '<bpmn:endEvent id="e1"/><bpmn:endEvent id="e2"/>')

    def _ends(self, body, **data):
        from ..workflow.engines import BpmnWorkflowEngine
        workflow = BpmnWorkflowEngine(xml_str=_process(
            '<bpmn:startEvent id="s"><bpmn:outgoing>a</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:sequenceFlow id="a" sourceRef="s" targetRef="pre"/>' + body)).get_workflow_obj_from_xml_parser()
        workflow.do_engine_steps()
        return sorted(t.task_spec.name for t in workflow.get_tasks()
                      if t.task_spec.name in ('e1', 'e2') and t.state == 64)

    def test_inclusive_gateway_takes_the_default_only_when_nothing_matches(self):
        self.assertEqual(self._ends(self.INCLUSIVE % '10'), ['e1'])
        self.assertEqual(self._ends(self.INCLUSIVE % '3'), ['e2'])

    def test_inclusive_gateway_needs_a_default_flow(self):
        without_default = self.INCLUSIVE.replace(' default="fd"', '').replace(
            '<bpmn:outgoing>fd</bpmn:outgoing>', '').replace(
            '<bpmn:sequenceFlow id="fd" sourceRef="g" targetRef="e2"/>', '')
        with self.assertRaises(UserError):
            self._save(without_default)

    def test_event_based_gateway_leads_only_to_receives_and_timers(self):
        def gateway(target):
            return ('<bpmn:eventBasedGateway id="eg" name="eg"><bpmn:outgoing>m1</bpmn:outgoing>'
                    '<bpmn:outgoing>t1</bpmn:outgoing></bpmn:eventBasedGateway>'
                    '<bpmn:sequenceFlow id="m1" sourceRef="eg" targetRef="rm"/>'
                    '<bpmn:sequenceFlow id="t1" sourceRef="eg" targetRef="%s"/>'
                    '<bpmn:receiveTask id="rm" name="rm" messageRef="Message_go"/>'
                    '<bpmn:intermediateCatchEvent id="tm" name="tm"><bpmn:timerEventDefinition>'
                    '<bpmn:timeDuration>\'PT1H\'</bpmn:timeDuration></bpmn:timerEventDefinition>'
                    '</bpmn:intermediateCatchEvent>') % target
        body = ('<bpmn:startEvent id="s"><bpmn:outgoing>a</bpmn:outgoing></bpmn:startEvent>'
                '<bpmn:sequenceFlow id="a" sourceRef="s" targetRef="eg"/>' + gateway("tm") +
                '<bpmn:sequenceFlow id="r1" sourceRef="rm" targetRef="e"/>'
                '<bpmn:sequenceFlow id="t2" sourceRef="tm" targetRef="e"/>'
                '<bpmn:endEvent id="e"/>')
        self._save(body, messages=self.MESSAGE)
        bad = ('<bpmn:startEvent id="s"><bpmn:outgoing>a</bpmn:outgoing></bpmn:startEvent>'
               '<bpmn:sequenceFlow id="a" sourceRef="s" targetRef="eg"/>' + gateway("sc") +
               '<bpmn:scriptTask id="sc" name="sc"><bpmn:script>x = 1</bpmn:script></bpmn:scriptTask>'
               '<bpmn:sequenceFlow id="r1" sourceRef="rm" targetRef="e"/>'
               '<bpmn:sequenceFlow id="t2" sourceRef="sc" targetRef="e"/>'
               '<bpmn:endEvent id="e"/>')
        with self.assertRaises(UserError):
            self._save(bad, messages=self.MESSAGE)

    def test_timers_can_be_dates_and_cycles(self):
        def timer(element, text):
            return ('<bpmn:intermediateCatchEvent id="t" name="t"><bpmn:timerEventDefinition>'
                    '<bpmn:%s>%s</bpmn:%s></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
                    % (element, text, element))
        self._save(_linear(timer('timeDate', "'2030-01-01T09:00:00'")))
        self._save(_linear(timer('timeCycle', "'R3/PT1H'")))
        for element, bad in (('timeDate', "'tomorrow'"), ('timeCycle', "'PT1H'"), ('timeDate', 'x')):
            with self.assertRaises(UserError):
                self._save(_linear(timer(element, bad)))

    # 边界定时器: 挂在自动节点上; 到期后取消该节点并走异常分支
    def _boundary(self, host_xml, attached):
        return ('<bpmn:startEvent id="s"><bpmn:outgoing>a</bpmn:outgoing></bpmn:startEvent>'
                '<bpmn:sequenceFlow id="a" sourceRef="s" targetRef="t"/>' + host_xml +
                '<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
                '<bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
                '<bpmn:boundaryEvent id="b" name="late" attachedToRef="%s"><bpmn:timerEventDefinition>'
                '<bpmn:timeDuration>\'PT1H\'</bpmn:timeDuration></bpmn:timerEventDefinition>'
                '<bpmn:outgoing>bo</bpmn:outgoing></bpmn:boundaryEvent>'
                '<bpmn:sequenceFlow id="bo" sourceRef="b" targetRef="e2"/>'
                '<bpmn:endEvent id="e2"><bpmn:incoming>bo</bpmn:incoming></bpmn:endEvent>') % attached

    def test_a_boundary_timer_attaches_to_an_automatic_task(self):
        receive = '<bpmn:receiveTask id="t" name="t" messageRef="Message_go"/>'
        self._save(self._boundary(receive, "t"), messages=self.MESSAGE)

    def test_a_boundary_timer_cannot_attach_to_an_approval(self):
        approval = ('<bpmn:userTask id="t" name="approve_execution"><bpmn:outgoing>f2</bpmn:outgoing>'
                    '</bpmn:userTask>')
        with self.assertRaises(UserError):
            self._save(self._boundary(approval, "t"))

    def test_a_boundary_timer_needs_an_existing_host(self):
        receive = '<bpmn:receiveTask id="t" name="t" messageRef="Message_go"/>'
        with self.assertRaises(UserError):
            self._save(self._boundary(receive, "missing"), messages=self.MESSAGE)

    def test_a_boundary_timer_takes_the_exception_path_when_the_task_waits_too_long(self):
        from ..workflow.engines import BpmnWorkflowEngine
        receive = '<bpmn:receiveTask id="t" name="t" messageRef="Message_go"/>'
        xml = _process(self._boundary(receive, "t"), messages=self.MESSAGE)
        workflow = BpmnWorkflowEngine(xml_str=xml).get_workflow_obj_from_xml_parser()
        workflow.do_engine_steps()
        self.assertFalse(workflow.is_completed())
        # 消息先到: 边界定时器被取消, 只走正常分支
        from ..gluon.bpmn.specs.events.event_definitions import MessageEventDefinition
        workflow.catch(MessageEventDefinition('go'))
        workflow.do_engine_steps()
        ends = sorted(t.task_spec.name for t in workflow.get_tasks()
                      if t.task_spec.name in ('e', 'e2') and t.state == 64)
        self.assertEqual(ends, ['e'])

    # 调用活动: 调用另一个流程定义 (被调用的流程中的审批与主流程一样推进)
    def _call_definitions(self):
        approver = self.env['res.users'].create({'name': 'callee approver', 'login': 'callee_approver'})
        called = self.env['snow.workflow.definition'].create({
            'name': 'called flow',
            'object_id': self.env.ref('base.model_res_users').id,
            'object_display_field': self.env['ir.model.fields'].search(
                [('model', '=', 'res.users'), ('name', '=', 'name')], limit=1).id,
            'target_view': self.env['ir.ui.view'].search(
                [('model', '=', 'res.users'), ('type', '=', 'form')], limit=1).id,
            'content': _process(_linear(
                '<bpmn:laneSet id="L"><bpmn:lane id="La" name="{\'user\': {\'domain\': [(\'id\', \'=\', %d)]}}">'
                '<bpmn:flowNodeRef>t</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>'
                '<bpmn:userTask id="t" name="approve_execution"/>' % approver.id)),
        })
        return approver, called

    def _call_flow(self, called_id):
        call = ('<bpmn:callActivity id="t" name="t" calledElement="call_%d"/>' % called_id)
        return _process(_linear(call))

    def test_a_call_activity_runs_the_called_approval(self):
        from ..workflow.snow_workflow import SnowWorkflow
        approver, called = self._call_definitions()
        self.definition.save_bpmn(self._call_flow(called.id))
        partner = self.env['res.partner'].create({'name': 'caller'})
        SnowWorkflow(self.env, self.env['snow.workflow.instance']).do_submit(
            instance=False, model='res.partner', record=partner.id)
        instance = self.env['snow.workflow.instance'].search(
            [('object', '=', 'res.partner'), ('record_id', '=', partner.id)], limit=1)
        execution = instance.wf_executions.filtered(lambda r: not r.is_complete)
        active = execution.wf_execution_tasks.filtered('in_progress')
        self.assertEqual(len(active), 1)
        self.assertEqual(active.task_attendee.user, approver)
        SnowWorkflow(self.env, instance).do_single_pass(
            instance=instance.id, task_name=active.task_xml_id, user=approver)
        instance.invalidate_recordset()
        self.assertTrue(instance.is_complete)

    def test_a_call_activity_must_call_an_existing_flow_that_calls_nothing(self):
        approver, called = self._call_definitions()
        with self.assertRaises(UserError):
            self.definition.save_bpmn(self._call_flow(9999999))
        with self.assertRaises(UserError):
            self.definition.save_bpmn(self._call_flow(self.definition.id))
        nested = called
        nested.content = self._call_flow(self.definition.id)
        with self.assertRaises(UserError):
            self.definition.save_bpmn(self._call_flow(nested.id))

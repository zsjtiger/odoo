# -*- coding: utf-8 -*-
import ast
import json
import re
import logging

from lxml import etree

from odoo import _, models, fields, api
from odoo.exceptions import UserError, ValidationError
from ..workflow import MY_APPROVED_TASKS_TYPE, STATUS_MAPPING
from ..workflow.engines import BpmnWorkflowEngine
from ..workflow.snow_workflow import SnowWorkflow

_logger = logging.getLogger(__name__)


# 新建流程定义时的空流程: 开始 -> 结束 (流程设计器中再完善)
EMPTY_PROCESS_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_main" targetNamespace="http://snow.workflow/bpmn">
  <bpmn:process id="main_process" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="flow_1" sourceRef="start_1" targetRef="end_1"/>
    <bpmn:endEvent id="end_1"><bpmn:incoming>flow_1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class WorkflowDefinition(models.Model):
    _name = 'snow.workflow.definition'
    _description = 'workflow definition'
    _table = 'snow_workflow_definition'
    _order = 'id'

    name = fields.Char(required=True, string="process name")
    description = fields.Char(string="process description")
    process_id = fields.Char(string="process id", required=True, readonly=True,
                             compute='_compute_bpmn_process_id')
    object = fields.Char(related='object_id.model', ondelete='cascade', store=False)
    object_display_field = fields.Many2one('ir.model.fields', string="object display field",
                                           required=True, ondelete='cascade')
    target_view = fields.Many2one('ir.ui.view', string="target view", required=True,
                                  ondelete='cascade')
    content = fields.Text(string="process content", required=True, widget='definition_content',
                          default=lambda self: EMPTY_PROCESS_BPMN)
    dmn_content = fields.Text(string="DMN decisions",
                              help="DMN XML with the decision tables used by business rule tasks.")

    @api.constrains('dmn_content')
    def _check_dmn_content(self):
        for record in self:
            if not record.dmn_content:
                continue
            try:
                BpmnWorkflowEngine.dmn_decision_ids(record.dmn_content)
            except Exception as error:
                raise ValidationError(_("The DMN decisions are not valid: %s", error)) from error
            error = record._dmn_expression_error(record.dmn_content)
            if error:
                raise ValidationError(_("The DMN decisions are not valid: %s", error))

    @staticmethod
    def _dmn_expression_error(dmn_str):
        """
        决策表的表达式在运行时按 Python 求值: 输入表达式与输出条目必须是表达式; 输入条目可以是比较
        (如 "> 5", 与引擎一致在前面补上变量), 或含 "?" 占位的表达式. 返回第一个错误的说明, 没有错误返回空.
        """
        def parses(candidate):
            try:
                ast.parse(candidate, mode='eval')
                return True
            except SyntaxError:
                return False

        root = etree.fromstring(dmn_str.encode('utf-8'))
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            name = etree.QName(element).localname
            if name not in ('inputExpression', 'inputEntry', 'outputEntry'):
                continue
            texts = [c for c in element if isinstance(c.tag, str) and etree.QName(c).localname == 'text']
            text = (texts[0].text or '').strip() if texts else ''
            if not text:
                # 空的输入条目表示匹配任何值
                continue
            if name == 'inputEntry':
                condition = text.replace('?', 'dmninputexpr')
                valid = parses(condition) or parses('v ' + condition)
            else:
                valid = parses(text)
            if not valid:
                return _("The expression “%s” is not valid Python.", text)
        return None

    version = fields.Integer(string="version")
    deployed_on = fields.Datetime(string='deployed on', required=True, default=fields.Datetime.now)
    active = fields.Boolean(string='active', default=True)
    is_internal_suspend = fields.Boolean(string='is internal suspend', default=False)
    is_external_suspend = fields.Boolean(string='is external suspend', default=False)
    can_add_attendee = fields.Boolean(string='can add attendee', default=False)
    attendee_domain = fields.Char(string='attendee domain')
    object_id = fields.Many2one('ir.model', string="object", required=True, ondelete='cascade',
                                domain="[('model', 'ilike', 'snow.%')]")
    deployed_by = fields.Many2one('res.users', string='deployed by',
                                  default=lambda self: self.env.user)
    instances = fields.One2many('snow.workflow.instance', 'wf_definition', string='instance')
    external_managers = fields.One2many(comodel_name="snow.workflow.external.managers",
                                        inverse_name="definition_id",
                                        string="external manager")
    submit_warning_type = fields.Selection([('no', 'direct submission'),
                                            ('inform', 'informed consent'),
                                            ('risk', 'risk warning + informed consent')],
                                           string="warning type", required=True, default='inform')
    informed_consent = fields.Text(string="informed consent")
    same_user_action = fields.Selection([('wait', 'duplicate approval'),
                                         ('follow', 'like first time')],
                                        string="same people action", required=True, default='wait')
    show_alert_before_reject = fields.Boolean(string='Show alert before reject', default=False)
    reject_alert_message = fields.Text(string="Reject alert message")
    show_alert_before_approval = fields.Boolean(string='Show alert before approval', default=False)
    approval_alert_message = fields.Text(string="Approval alert message")

    @api.onchange('object_id')
    def compute_domain(self):
        for record in self:
            if record.object_id:
                name_domain = [('model_id', '=', record.object_id.id)]
                view_domain = [('model', '=', record.object_id.model), ('type', '=', 'form')]
            else:
                # 不选object_id，不显示任何选项
                name_domain = [('model_id', '=', '')]
                view_domain = [('id', '=', 0)]
            record.object_display_field = False
            record.target_view = False
            return {'domain': {'object_display_field': name_domain, 'target_view': view_domain}}

    @api.depends('content')
    def _compute_bpmn_process_id(self):
        """
        解析bpmn内容，获得def_id的值
        """
        for record in self:
            # avoid loading on the list page
            if not record.process_id and record.content:
                content_xml = record.content
                if content_xml:
                    bpmn_workflow_engine = BpmnWorkflowEngine(xml_str=content_xml)
                    record.process_id = bpmn_workflow_engine.parser.get_process_ids()[0]
                else:
                    record.process_id = ''

    def unlink(self):
        """
        删除definition前判断，是否有关联的instance
        """
        for record in self:
            if self.env['snow.workflow.instance'].search_count([('wf_definition', '=',
                                                                    record.id)]):
                raise ValidationError("Cannot delete record with related records. "
                                      "Please remove related records first.")
        # Continue with the deletion if no related records
        return super(WorkflowDefinition, self).unlink()

    def fetch_definition(self, model, record):
        """
        为支持不同record_type对应不同工作流，snow_common中重写此方法
        :return:
        """
        print(record)
        return self.sudo().search([('object', '=', model)])

    def action_open_designer(self):
        """
        打开流程设计器 (表单中的按钮)
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'snow_workflow_designer',
            'name': _('Process designer'),
            'target': 'current',
            'params': {'definition_id': self.id},
        }

    # 设计器支持的审批任务类型 (与 static/src/designer/bpmn_model.js 保持一致)
    DESIGNER_APPROVAL_TYPES = {'approve_execution', 'group_approve_execution_or',
                               'group_approve_execution_and'}
    # 流程级允许的子元素 (节点与连线另行检查)
    DESIGNER_SCOPE_EXTRAS = {'laneSet', 'documentation', 'extensionElements', 'incoming', 'outgoing'}
    # 设计器支持的节点 (审批节点与定时器另行判断)
    DESIGNER_NODE_TAGS = {'startEvent', 'endEvent', 'parallelGateway', 'exclusiveGateway', 'inclusiveGateway',
                          'eventBasedGateway', 'serviceTask', 'subProcess', 'scriptTask', 'businessRuleTask',
                          'sendTask', 'receiveTask', 'callActivity'}
    # 边界定时器可以挂在这些自动节点上 (审批节点不行: 取消时无法同步审批记录)
    BOUNDARY_HOSTS = ('serviceTask', 'scriptTask', 'businessRuleTask', 'sendTask', 'receiveTask')
    # 只有这些节点可以有多条出线 (分支与并行必须经过网关)
    DESIGNER_GATEWAYS = ('exclusiveGateway', 'inclusiveGateway', 'parallelGateway', 'eventBasedGateway')
    ISO_DURATION_RE = re.compile(r'^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?$')
    ISO_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$')
    ISO_CYCLE_RE = re.compile(r'^R\d*/P(?!$)[0-9YMWDTHS.,]+$')
    BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
    CAMUNDA_NS = 'http://camunda.org/schema/1.0/bpmn'

    def _check_designer_limits(self, content):
        """
        设计器的限制: 只允许支持的元素; 每个流程/子流程有且只有一个开始事件、至少一个结束事件;
        除开始与结束外的节点必须有入线与出线; 排他网关的条件合法, 服务任务的操作已注册
        """
        root = etree.fromstring(content.encode('utf-8'))
        process = next(el for el in root.iter() if etree.QName(el).localname == 'process')
        self._check_designer_scope(process)

    # 调用活动: calledElement="call_<定义 id>"; 被调用的定义只能是一层 (不能再调用其它流程)
    CALL_PREFIX = 'call_'
    CALLED_ELEMENT_RE = re.compile(r'calledElement="call_(\d+)"')

    def _called_definition_ids(self, content):
        return sorted({int(i) for i in self.CALLED_ELEMENT_RE.findall(content or '')})

    def _called_extras(self):
        """调用活动需要的被调用流程 (bpmn, dmn): 流程 id 改为 call_<定义 id>, 避免与主流程冲突"""
        extras = []
        for called in self.browse(self._called_definition_ids(self.content)).sudo():
            xml = re.sub(r'(<bpmn:process\b[^>]*\bid=")main_process(")',
                         lambda m: f'{m.group(1)}{self.CALL_PREFIX}{called.id}{m.group(2)}', called.content, count=1)
            extras.append((xml, called.dmn_content))
        return extras

    def _dmn_decision_ids(self):
        """定义中 DMN 的决策 id (业务规则任务的 decisionRef 只能引用这些)"""
        if not self.dmn_content:
            return set()
        return BpmnWorkflowEngine.dmn_decision_ids(self.dmn_content)

    def _check_designer_scope(self, scope):
        from ..workflow.service_operations import SERVICE_OPERATIONS

        def local(el):
            return etree.QName(el).localname

        root = scope.getroottree().getroot()
        messages = {m.get('id'): m.get('name') for m in root.iter(f'{{{self.BPMN_NS}}}message')}
        decisions = self._dmn_decision_ids()

        nodes, flows = {}, []
        for child in scope:
            if not isinstance(child.tag, str):
                continue
            name = local(child)
            if name == 'userTask' and child.get('name') in self.DESIGNER_APPROVAL_TYPES:
                nodes[child.get('id')] = child
            elif name in ('intermediateCatchEvent', 'boundaryEvent') and child.find(
                    f'{{{self.BPMN_NS}}}timerEventDefinition') is not None:
                nodes[child.get('id')] = child
            elif name == 'intermediateThrowEvent' and not len(
                    [c for c in child if isinstance(c.tag, str) and etree.QName(c).localname.endswith('EventDefinition')]):
                # 中间抛出事件 (无定义): 直接通过, 不发送消息
                nodes[child.get('id')] = child
            elif name in self.DESIGNER_NODE_TAGS:
                nodes[child.get('id')] = child
            elif name == 'sequenceFlow':
                flows.append(child)
            elif name not in self.DESIGNER_SCOPE_EXTRAS:
                raise UserError(_("These elements are not supported by the process designer: %s",
                                  f"{name} ({child.get('name') or child.get('id')})"))

        kinds = {node_id: self._designer_kind(el) for node_id, el in nodes.items()}
        for node_id, el in nodes.items():
            if kinds[node_id] == 'boundary_timer':
                host = el.get('attachedToRef')
                if host not in nodes or kinds[host] not in self.BOUNDARY_HOSTS:
                    raise UserError(_("The boundary timer “%s” must be attached to a service, script, "
                                      "business rule, send or receive task.", el.get('name') or node_id))
        starts = [i for i, k in kinds.items() if k == 'startEvent']
        ends = [i for i, k in kinds.items() if k == 'endEvent']
        if len(starts) != 1:
            raise UserError(_("A process or subprocess needs exactly one start event."))
        if not ends:
            raise UserError(_("A process or subprocess needs at least one end event."))

        targets = {f.get('targetRef') for f in flows}
        sources = {f.get('sourceRef') for f in flows}
        for node_id, kind in kinds.items():
            label = nodes[node_id].get('name') or node_id
            if kind not in ('startEvent', 'boundary_timer') and node_id not in targets:
                raise UserError(_("“%s” has no incoming flow.", label))
            if kind != 'endEvent' and node_id not in sources:
                raise UserError(_("“%s” has no outgoing flow.", label))
            outgoing_count = len([f for f in flows if f.get('sourceRef') == node_id])
            if kind not in self.DESIGNER_GATEWAYS and outgoing_count > 1:
                # 多条出线会被引擎当作隐式分支, 分支必须使用网关
                raise UserError(_("“%s” can have only one outgoing flow; use a gateway to split the flow.", label))
            element = nodes[node_id]
            self._check_multi_instance(element, kind)
            if kind in ('exclusiveGateway', 'inclusiveGateway'):
                self._check_exclusive_gateway(element, [f for f in flows if f.get('sourceRef') == node_id])
            elif kind == 'eventBasedGateway':
                self._check_event_based_gateway(element, [f for f in flows if f.get('sourceRef') == node_id], kinds)
            elif kind == 'serviceTask':
                self._check_service_task(element, SERVICE_OPERATIONS)
            elif kind == 'scriptTask':
                self._check_script_task(element)
            elif kind == 'businessRuleTask':
                self._check_business_rule_task(element, decisions)
            elif kind in ('sendTask', 'receiveTask'):
                self._check_message_task(element, messages)
            elif kind in ('timer', 'boundary_timer'):
                self._check_timer_event(element)
            elif kind == 'callActivity':
                self._check_call_activity(element)
            elif kind == 'subProcess':
                self._check_designer_scope(element)

    def _designer_kind(self, element):
        """节点在设计器中的类型: 定时器是带 timerEventDefinition 的中间捕获事件或边界事件"""
        name = etree.QName(element).localname
        if name == 'intermediateCatchEvent':
            return 'timer'
        if name == 'boundaryEvent':
            return 'boundary_timer'
        return name

    def _check_multi_instance(self, element, kind):
        """多实例只用于自动任务 (服务任务、脚本任务): 审批节点的多人审批由审批模型处理, 不做多实例"""
        loop = element.find(f'{{{self.BPMN_NS}}}multiInstanceLoopCharacteristics')
        if loop is None:
            return
        label = element.get('name') or element.get('id')
        if kind not in ('serviceTask', 'scriptTask'):
            raise UserError(_("Multi-instance is only supported on service and script tasks, not on “%s”.", label))
        if loop.get('isSequential') not in (None, 'true', 'false'):
            raise UserError(_("The sequential flag of “%s” must be true or false.", label))
        cardinality = loop.find(f'{{{self.BPMN_NS}}}loopCardinality')
        text = (cardinality.text or '').strip() if cardinality is not None else ''
        if not text:
            raise UserError(_("The multi-instance task “%s” needs a cardinality.", label))
        try:
            ast.parse(text, mode='eval')
        except SyntaxError as error:
            raise UserError(_("The cardinality “%(expr)s” of “%(task)s” is not valid: %(error)s",
                              expr=text, task=label, error=error.msg)) from error

    def _check_script_task(self, element):
        label = element.get('name') or element.get('id')
        script = element.find(f'{{{self.BPMN_NS}}}script')
        text = (script.text or '').strip() if script is not None else ''
        if not text:
            raise UserError(_("The script task “%s” needs a script.", label))
        try:
            compile(text, label, 'exec')
        except SyntaxError as error:
            raise UserError(_("The script of “%(task)s” is not valid Python: %(error)s",
                              task=label, error=error.msg)) from error

    def _check_business_rule_task(self, element, decisions):
        label = element.get('name') or element.get('id')
        ref = element.get(f'{{{self.CAMUNDA_NS}}}decisionRef')
        if not ref:
            raise UserError(_("The business rule task “%s” needs a decision.", label))
        if ref not in decisions:
            raise UserError(_("The decision “%(decision)s” of “%(task)s” is not defined in the DMN decisions.",
                              decision=ref, task=label))
        result = element.get(f'{{{self.CAMUNDA_NS}}}resultVariable')
        if result is not None and not result.isidentifier():
            raise UserError(_("The result variable of “%s” must be a valid name.", label))

    def _check_call_activity(self, element):
        label = element.get('name') or element.get('id')
        ref = element.get('calledElement') or ''
        match = re.match(r'^call_(\d+)$', ref)
        if not match:
            raise UserError(_("The call activity “%s” needs a process to call.", label))
        called = self.browse(int(match.group(1))).sudo()
        if not called.exists() or called.id == self.id:
            raise UserError(_("The call activity “%s” must call another existing process.", label))
        if self._called_definition_ids(called.content):
            raise UserError(_("The process called by “%s” cannot call other processes.", label))

    def _check_message_task(self, element, messages):
        label = element.get('name') or element.get('id')
        ref = element.get('messageRef')
        if not ref or not messages.get(ref):
            raise UserError(_("The message task “%s” needs a message.", label))
        target = self._target_record_expression(element)
        if target is not None:
            try:
                ast.parse(target, mode='eval')
            except SyntaxError as error:
                raise UserError(_("The target record of “%(task)s” is not valid: %(error)s",
                                  task=label, error=error.msg)) from error

    def _target_record_expression(self, element):
        """发送消息的目标记录表达式 (camunda:property targetRecord); 没有则返回 None"""
        for prop in element.iter(f'{{{self.CAMUNDA_NS}}}property'):
            if prop.get('name') == 'targetRecord':
                return (prop.get('value') or '').strip() or None
        return None

    def _check_event_based_gateway(self, gateway, outgoing, kinds):
        """事件网关: 之后只能是接收任务或定时器 (由先发生的事件决定走哪一条)"""
        label = gateway.get('name') or gateway.get('id')
        if len(outgoing) < 2:
            raise UserError(_("The event-based gateway “%s” needs at least two outgoing flows.", label))
        for flow in outgoing:
            if kinds.get(flow.get('targetRef')) not in ('receiveTask', 'timer'):
                raise UserError(_("After the event-based gateway “%s” only receive tasks and timers are allowed.",
                                  label))

    def _check_timer_event(self, element):
        """
        定时器: 时长 timeDuration (ISO 8601 时长), 日期 timeDate (ISO 日期时间), 循环 timeCycle (R[n]/时长).
        表达式以 Python 字符串书写, 如 'PT1H'.
        """
        label = element.get('name') or element.get('id')
        timer = element.find(f'{{{self.BPMN_NS}}}timerEventDefinition')
        for tag, pattern, hint in (
            ('timeDuration', self.ISO_DURATION_RE, "e.g. 'PT1H'"),
            ('timeDate', self.ISO_DATETIME_RE, "e.g. '2030-01-01T09:00:00'"),
            ('timeCycle', self.ISO_CYCLE_RE, "e.g. 'R3/PT1H'"),
        ):
            child = timer.find(f'{{{self.BPMN_NS}}}{tag}')
            if child is None:
                continue
            text = (child.text or '').strip()
            try:
                value = ast.literal_eval(text)
            except (ValueError, SyntaxError) as error:
                raise UserError(_("The time of “%(task)s” must be a string in quotes, %(hint)s.",
                                  task=label, hint=hint)) from error
            if not isinstance(value, str) or not pattern.match(value):
                raise UserError(_("The time of “%(task)s” is not valid, %(hint)s.", task=label, hint=hint))
            return
        raise UserError(_("The timer “%s” has no time.", label))

    def _check_exclusive_gateway(self, gateway, outgoing):
        label = gateway.get('name') or gateway.get('id')
        if not outgoing:
            raise UserError(_("“%s” has no outgoing flow.", label))
        default = gateway.get('default')
        if len(outgoing) > 1 and not default:
            raise UserError(_("“%s” needs a default flow.", label))
        if default and default not in {f.get('id') for f in outgoing}:
            raise UserError(_("The default flow of “%s” is not one of its outgoing flows.", label))
        for flow in outgoing:
            if flow.get('id') == default:
                continue
            condition = flow.find(f'{{{self.BPMN_NS}}}conditionExpression')
            text = (condition.text or '').strip() if condition is not None else ''
            if not text:
                raise UserError(_("The flow of “%s” needs a condition.", label))
            try:
                ast.parse(text, mode='eval')
            except SyntaxError as error:
                raise UserError(_("The condition “%(condition)s” is not a valid expression: %(error)s",
                                  condition=text, error=error.msg)) from error

    def _check_service_task(self, task, operations):
        from ..workflow.service_operations import check_writable_field

        label = task.get('name') or task.get('id')
        raw = None
        for prop in task.iter(f'{{{self.CAMUNDA_NS}}}property'):
            if prop.get('name') == 'serviceTaskOperator':
                raw = prop.get('value')
        try:
            operator = json.loads(raw or 'null')
        except ValueError:
            operator = None
        if not isinstance(operator, dict) or not operator.get('name'):
            raise UserError(_("The service task “%s” needs an operation.", label))
        if operator['name'] not in operations:
            raise UserError(_("Unknown service operation “%(operation)s” of “%(task)s”.",
                              operation=operator['name'], task=label))
        parameters = operator.get('parameters') or {}
        if operator['name'] == 'evaluate' and 'value' not in parameters:
            raise UserError(_("The operation of “%s” needs a value.", label))
        for name, param in parameters.items():
            if not isinstance(param, dict) or not isinstance(param.get('value'), str):
                raise UserError(_("The parameter “%s” of “%s” needs an expression.", name, label))
            try:
                ast.parse(param['value'], mode='eval')
            except SyntaxError as error:
                raise UserError(_("The expression “%(expr)s” is not valid: %(error)s",
                                  expr=param['value'], error=error.msg)) from error
            if operator['name'] == 'write_record':
                check_writable_field(self.env, self.object_id.model, name)
        result = operator.get('resultVariable')
        if result is not None and not (isinstance(result, str) and result.isidentifier()):
            raise UserError(_("The result variable of “%s” must be a valid name.", label))

    def save_bpmn(self, content):
        """
        流程设计器保存: 先用引擎解析校验, 通过后再写入 content (process_id 由 content 计算)

        :param content: BPMN XML 字符串
        """
        self.ensure_one()
        self.check_access('write')
        try:
            engine = BpmnWorkflowEngine(xml_str=content, dmn_str=self.dmn_content, called=self._called_extras())
            process_ids = engine.parser.get_process_ids()
            engine._get_workflow_all_specs_from_xml_parser()
        except Exception as error:
            raise UserError(_("The process is not a valid BPMN diagram: %s", error)) from error
        if 'main_process' not in process_ids:
            raise UserError(_("The diagram must contain the process with id “main_process”."))
        self._check_designer_limits(content)
        if 'scriptTask' in content and not self.env.user.has_group('base.group_system'):
            # 脚本任务执行任意 Python, 只允许系统管理员编辑
            raise UserError(_("Only system administrators can add script tasks to a process."))
        self.write({'content': content})
        return True


class WorkflowExternalManagers(models.Model):
    _name = 'snow.workflow.external.managers'
    _description = 'external manager'
    _table = 'snow_workflow_external_managers'
    _order = 'id'

    definition_id = fields.Many2one(comodel_name="snow.workflow.definition", string="definition id",
                                    readonly=True)
    user_id = fields.Many2one(comodel_name="res.users", string="user id", auto_join=True)


class WorkflowActionMixin(models.AbstractModel):
    _name = 'snow.workflow.action.mixin'
    _description = 'workflow action mixin'
    task_name = fields.Char(string='task name', compute='_compute_task_name', search='_search_task_name', store=False)

    @api.depends('object')
    def _compute_task_name(self):
        """
        计算业务模块的显示名称
        :return:
        """
        for record in self:
            definition = getattr(record, 'wf_instance').wf_definition
            record_id = getattr(record, 'record_id')
            if definition and record_id:
                target_data = self.env[record.object].browse(record_id)
                task_name = getattr(target_data, definition.object_display_field.name)
                record.task_name = task_name
            else:
                record.task_name = ''

    def _search_task_name(self, operator, value):
        if operator not in ('=', '!=', 'ilike'):
            raise ValidationError("Unsupported operator for task name")

        matched_ids = []
        candidates = self.search(
            [('wf_instance.wf_definition', '!=', False), ('record_id', '!=', False)])
        for record in candidates:
            try:
                target_value = record.task_name
                if value:
                    if operator == '=' and value.lower() == str(target_value).lower():
                        matched_ids.append(record.id)

                    if operator == 'ilike' and value.lower() in str(target_value).lower():
                        matched_ids.append(record.id)

                    if operator == '!=' and value.lower() != str(target_value).lower():
                        matched_ids.append(record.id)
                elif operator == '=' and (str(target_value).lower() == '' or not target_value):
                    # 搜索字段为空
                    matched_ids.append(record.id)

            except Exception:
                continue
        return [('id', 'in', matched_ids)]

    def dynamic_redirect(self):
        """
        查看按钮，跳转业务模块form页面

        :return: 页面action
        """
        for record in self:
            self.clean_context_type()
            # 去掉原有逻辑，不再判断业务数据是否已经删除
            action = {
                'type': 'ir.actions.act_window',
                'name': 'Dynamic Redirect',
                'res_model': record.object,
                'res_id': record.record_id,
                'view_mode': 'form',
                'target': 'current',
            }
            if hasattr(record, 'wf_execution'):
                execution_id = getattr(record, 'wf_execution').id
                action.update({'context': {'execution_id': execution_id}})
            elif isinstance(record, WorkflowExecution):
                action.update({'context': {'execution_id': record.id}})
            definition = getattr(record, 'wf_instance').wf_definition
            action['view_id'] = definition.target_view.id
            action['views'] = [
                (definition.target_view.id, 'form'),
            ]
            return action

    @api.model
    def search_count(self, args):
        # 与 search 使用同样的数据范围
        res = len(self.search(args))
        self.clean_context_type()
        return res

    @api.model
    def search(self, args, offset=0, limit=None, order=None):
        """
        扩展父类search方法，限定审批流控制台的数据范围

        :return: 父类search方法
        """
        _type = self.env.context.get("_type")
        _args = []

        # 我发起的  snow.workflow.execution
        if _type == "own_approval" and isinstance(self, WorkflowExecution):
            _args = [('wf_instance.initiator.id', '=', self.env.uid),
                     ('status', '!=', 'approve_draft')]

        # 已完成
        elif _type == "approved" and isinstance(self, WorkflowExecutionTaskHistory):
            _args = [('user_id', '=', self.env.uid),
                     ('task_xml_name', 'in', MY_APPROVED_TASKS_TYPE),
                     ('wf_instance.status', '!=', 'withdraw')]

        # 待我审批
        elif _type == "wait_approval" and isinstance(self, WorkflowExecutionTask):
            _args = self.get_pending_args()

        # 抄送我的
        elif _type == "copy_to_me" and isinstance(self, WorkflowCarbonCopy):
            _args = [('copy_user', '=', self.env.uid)]

        # self.clean_context_type()

        _args.extend(args)
        return super(WorkflowActionMixin, self).search(_args, offset=offset, limit=limit, order=order)

    def get_pending_args(self):
        filtered_domain = [('user', '=', self.env.uid),
                           '|',
                           ('is_assigner', '!=', True),
                           '&', ('is_assigner', '=', True), ('assigner_state', '=', 1)
                           ]
        task_list = self.env['snow.workflow.execution.task.attendee'].sudo().search(
            filtered_domain).mapped('wf_task.id')
        return [('in_progress', '=', True),
                 ('id', 'in', task_list)]

    def clean_context_type(self):
        mutable_context = self.env.context.copy()
        mutable_context['_type'] = ''
        self.env.context = mutable_context


class WorkflowInstance(models.Model):
    _name = 'snow.workflow.instance'
    _description = 'Workflow Instance'
    _table = 'snow_workflow_instance'
    _order = 'id'

    start_time = fields.Datetime(string='start time')
    end_time = fields.Datetime(string='end time')
    record_id = fields.Integer(string="related record id")
    # wf_json = fields.Text(string="工作流描述JSON")
    is_complete = fields.Boolean(string="is complete")
    object = fields.Char(string='approval type', related='wf_definition.object_id.model',
                         store=True)
    object_name = fields.Char(string='模块名', compute='_compute_object_name')
    status = fields.Char(string='workflow status')
    status_owner = fields.Many2one('res.users')
    status_name = fields.Char(string='status name', compute='_compute_status_name', store=False)
    initiator = fields.Many2one('res.users', string='initiator',
                                default=lambda self: self.env.uid, ondelete='set null')
    wf_definition = fields.Many2one('snow.workflow.definition', string='workflow definition')
    wf_executions = fields.One2many('snow.workflow.execution', 'wf_instance', string='execution')
    suspend_info = fields.One2many('snow.workflow.instance.suspend', 'wf_instance',
                                   string="suspend info")
    business_deleted = fields.Boolean(string="business data deleted",
                                      compute='_compute_business_data_deleted', store=False)

    @api.depends('wf_definition')
    def _compute_object_name(self):
        for record in self:
            if self.wf_definition.object_id.name:
                record.object_name = self.wf_definition.object_id.name

    @api.depends('status', 'status_owner')
    def _compute_status_name(self):
        for record in self:
            status_owner = record.status_owner.name if bool(record.status_owner.id) else None
            record.status_name = ((status_owner if status_owner else '') +
                                  STATUS_MAPPING.get(record.status))

    @api.depends('object', 'record_id')
    def _compute_business_data_deleted(self):
        for record in self:
            business_data = self.env[self.object].sudo().search([('id', '=', self.record_id)])
            if business_data:
                record.business_deleted = business_data.deleted
            else:
                record.business_deleted = False

    def update_record_field(self, changed=True):
        """
        更新业务模型字段，按顺序调用业务模块指定回调函数
        """
        search_condition = [('object_id', '=', self.wf_definition.object_id.id),
                            ('wf_state', '=', self.status)]
        state_mapping = self.env["snow.workflow.state.mapping"].search(search_condition)
        business_record = self.env[self.wf_definition.object_id.model].browse([self.record_id])
        for state_record in state_mapping:
            if (state_record.object_field_name and hasattr(business_record,
                                                           state_record.object_field_name) and
                    state_record.object_field_value):
                update_value = state_record.object_field_value \
                    if not state_record.object_field_value.isnumeric() \
                    else int(state_record.object_field_value)
                business_record.write({state_record.object_field_name: update_value})
            elif (state_record.object_field_name and
                  hasattr(business_record, state_record.object_field_name) and
                  state_record.instance_field_name and
                  hasattr(self, state_record.instance_field_name)):
                business_record.write({state_record.object_field_name: getattr(
                    self, state_record.instance_field_name)})
        # 当状态改变时再执行action
        if changed:
            order_action = self.env['snow.workflow.state.action'].sudo().search(search_condition,
                                                                                order='order')
            for action in order_action:
                if hasattr(business_record, action.action):
                    method = getattr(business_record, action.action)
                    if callable(method):
                        method()

    def write(self, vals):
        changed = False
        if 'status' in vals:
            changed = self.status != vals['status']
        # 判断status是否有变更，有变更则对业务模块状态做更新
        result = super().write(vals)
        if 'status' in vals:
            self.update_record_field(changed)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        res = super(WorkflowInstance, self).create(vals_list)
        res.update_record_field()
        return res


class WorkflowInstanceSuspend(models.Model):
    _name = 'snow.workflow.instance.suspend'
    _description = 'suspend instance'
    _table = 'snow_workflow_instance_suspend'
    _order = 'id'

    suspend_time = fields.Datetime(string="suspend time")
    suspend_user = fields.Many2one('res.users', string="suspend user")
    wf_instance = fields.Many2one('snow.workflow.instance', string="workflow instance")


class WorkflowInstanceSuspendHistory(models.Model):
    _name = 'snow.workflow.instance.suspend.history'
    _description = 'workflow instance suspend history'
    _table = 'snow_workflow_instance_suspend_history'
    _order = 'id'

    suspend_time = fields.Datetime(string="suspend time")
    unsuspend_time = fields.Datetime(string="unsuspend time")
    wf_instance = fields.Many2one('snow.workflow.instance', string="workflow instance")
    suspend_user = fields.Many2one('res.users', string="suspend user")


class WorkflowExecution(models.Model):
    _name = 'snow.workflow.execution'
    _inherit = ['snow.workflow.action.mixin']
    _description = 'workflow execution'
    _table = 'snow_workflow_execution'
    _order = 'id'

    @api.model
    def _cron_advance_timers(self):
        """
        定时任务: 推进等待中的定时器, 到期后流程继续 (不经过用户审批).
        挂起或挂起中的流程不推进; 单个流程失败只记录日志, 不影响其他流程.
        """
        executions = self.sudo().search([('is_complete', '=', False)])
        for execution in executions:
            if execution.wf_instance.suspend_info:
                continue
            try:
                with self.env.cr.savepoint():
                    SnowWorkflow(self.env, execution.wf_instance).advance_timers()
            except Exception:
                _logger.exception("Failed to advance timers of workflow execution %s", execution.id)

    # static: execution对象填充
    wf_json = fields.Text(string="workflow description JSON")
    is_complete = fields.Boolean(string='is complete')
    status = fields.Char(string='execution status')
    status_owner = fields.Many2one('res.users')
    object = fields.Char(string="related object", related="wf_instance.object", store=False)
    record_id = fields.Integer(string="record id", related="wf_instance.record_id", store=False)
    status_name = fields.Char(string='status name', compute='_compute_status_name', store=False)
    submitter_name = fields.Char(string="submitter", related="wf_instance.initiator.name",
                                 store=False)
    object_name = fields.Char(string='object name', related='wf_instance.object_name', store=False)
    # static: 额外计算
    vision_data = fields.Text(string="vision data")

    # relation
    wf_instance = fields.Many2one('snow.workflow.instance', string='workflow instance')
    wf_execution_tasks = fields.One2many('snow.workflow.execution.task', 'wf_execution')
    wf_execution_tasks_history = fields.One2many('snow.workflow.execution.task.history',
                                                 'wf_execution')

    @api.depends('status', 'status_owner')
    def _compute_status_name(self):
        for record in self:
            owner = record.status_owner.name if record.status_owner.name else ''
            record.status_name = owner + STATUS_MAPPING.get(record.status)


class WorkflowExecutionTaskHistory(models.Model):
    _name = 'snow.workflow.execution.task.history'
    _inherit = ['snow.workflow.action.mixin']
    _description = 'execution task history'
    _table = 'snow_workflow_execution_task_history'
    _order = 'id'

    # static: task对象填充
    task_xml_id = fields.Char(string='task xml_id')  # task_name == task_xml_id
    task_xml_name = fields.Char(string='task xml_name')  # task_description == task_xml_name
    wf_task_json = fields.Text(string="task description json")
    wf_task_spec_json = fields.Text(string="task spec description json")

    # relation
    wf_task = fields.Many2one('snow.workflow.execution.task', string="task")
    wf_execution = fields.Many2one('snow.workflow.execution', string='related execution')
    wf_instance = fields.Many2one('snow.workflow.instance', related='wf_execution.wf_instance',
                                  string='related instance', store=True)
    task_attendee_history = fields.One2many('snow.workflow.execution.task.attendee.history',
                                            'wf_task_history', string='task executor')

    # extra
    user_id = fields.Integer(related="task_attendee_history.user.id", store=False)
    object = fields.Char(string="related object", related="wf_instance.object", store=False)
    object_name = fields.Char(string='object name', related='wf_instance.object_name', store=True)
    submitter_name = fields.Char(string="Submitter", related="wf_instance.initiator.name",
                                 store=False)
    record_id = fields.Integer(string="record id", related="wf_instance.record_id", store=False)
    status_name = fields.Char(string="status name", related="wf_execution.status_name", store=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super(WorkflowExecutionTaskHistory, self).create(vals_list)


class WorkflowExecutionTask(models.Model):
    _name = 'snow.workflow.execution.task'
    _inherit = ['snow.workflow.action.mixin']
    _description = 'Execution Task'
    _table = 'snow_workflow_execution_task'
    _order = 'id'

    # static: task对象填充
    task_xml_id = fields.Char(string='task xml_id')  # task_name == task_xml_id
    task_xml_name = fields.Char(string='task xml_name')  # task_description == task_xml_name
    wf_task_json = fields.Text(string="task description json")
    wf_task_spec_json = fields.Text(string="task spec description json")
    in_progress = fields.Boolean(string="in progress")

    task_attendee = fields.One2many('snow.workflow.execution.task.attendee', 'wf_task',
                                    string='task executor')
    wf_execution = fields.Many2one('snow.workflow.execution', string='related execution')
    wf_instance = fields.Many2one('snow.workflow.instance', related='wf_execution.wf_instance',
                                  string='related instance', store=True)

    # extra
    object = fields.Char(string="related object", related="wf_instance.object", store=False)
    object_name = fields.Char(string='object name', related='wf_instance.object_name', store=True)
    submitter_name = fields.Char(string="Submitter", related="wf_instance.initiator.name",
                                 store=False)
    record_id = fields.Integer(string="record id", related="wf_instance.record_id", store=False)
    status_name = fields.Char(string="status name", related="wf_instance.status_name", store=False)

    @api.model_create_multi
    def create(self, vals):
        return super(WorkflowExecutionTask, self).create(vals)

    def unlink(self):
        # 拼domain实现多条级联删除
        domain = [("wf_task", "in", [record.id for record in self])]
        self.env['snow.workflow.execution.task.attendee'].search(domain).unlink()

        return super(WorkflowExecutionTask, self).unlink()

    @api.model
    def get_pending_count(self):
        args = self.get_pending_args()
        return self.search_count(args)


class WorkflowExecutionTaskData(models.Model):
    _name = 'snow.workflow.execution.task.data'
    _description = 'Task Execution Data'
    _table = 'snow_workflow_execution_task_data'
    _order = 'id'

    wf_task = fields.Many2one('snow.workflow.execution.task', string="task")
    wf_task_history = fields.Many2one('snow.workflow.execution.task.history')
    data_owner = fields.Many2one('res.users')
    name = fields.Char(string='variable name', required=True)
    value = fields.Char(string='variable value', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        return super(WorkflowExecutionTaskData, self).create(vals_list)

    @api.model
    def create_data_for_task(self, wf_instance, name, value, user):
        task = self.env['snow.workflow.execution.task'].with_context(_type='').sudo().search(
            [('wf_instance', '=', wf_instance), ('in_progress', '=', True)])
        if task:
            task_data = {'wf_task': task.id,
                         'name': name,
                         'value': value,
                         'data_owner': user.id
                         }
            self.create(task_data)


class WorkflowExecutionTaskAttendee(models.Model):
    _name = 'snow.workflow.execution.task.attendee'
    _description = 'Task Attendee'
    _table = 'snow_workflow_execution_task_attendee'
    _order = 'id'

    user = fields.Many2one('res.users', string='user')
    wf_task = fields.Many2one('snow.workflow.execution.task', string="task")
    is_assigner = fields.Boolean(string="is assigner")
    # 0 等待开始  1 已开始  2 已结束
    assigner_state = fields.Integer(string="assigner state")
    submitter_name = fields.Char(string="Submitter", related="wf_task.submitter_name", store=False)
    record_id = fields.Integer(string="record id", related="wf_task.record_id", store=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super(WorkflowExecutionTaskAttendee, self).create(vals_list)


class WorkflowExecutionTaskAttendeeHistory(models.Model):
    _name = 'snow.workflow.execution.task.attendee.history'
    _description = 'Task Attendee History'
    _table = 'snow_workflow_execution_task_attendee_history'
    _order = 'id'

    user = fields.Many2one('res.users', string='user')
    wf_task_history = fields.Many2one('snow.workflow.execution.task.history', string='task history')
    action = fields.Char(string='user action')

    @api.model_create_multi
    def create(self, vals_list):
        return super(WorkflowExecutionTaskAttendeeHistory, self).create(vals_list)


class WorkflowStateMapping(models.Model):
    _name = 'snow.workflow.state.mapping'
    _description = 'workflow state mapping'
    _table = 'snow_workflow_state_mapping'
    _order = 'id'

    object_id = fields.Char(string="related object")
    object_field_name = fields.Char(string="related object name")
    object_field_value = fields.Char(string="related object value")
    instance_field_name = fields.Char(string="workflow instance name")
    wf_state = fields.Char("workflow status")

    @api.model_create_multi
    def create(self, vals_list):
        return super(WorkflowStateMapping, self).create(vals_list)


class WorkflowStateAction(models.Model):
    """
        当审批流状态变更为某值时，回调业务模块某方法，暂无参数传递
        例如：审批状态完成时，调用业务模块pass方法
    """
    _name = 'snow.workflow.state.action'
    _description = 'workflow state action'
    _table = 'snow_workflow_state_action'
    _order = 'id'

    object_id = fields.Char(string="related object")
    action = fields.Char(string="callback function")
    order = fields.Integer(string="action order")
    wf_state = fields.Char("workflow status")


class WorkflowCarbonCopy(models.Model):
    _name = 'snow.workflow.carbon.copy'
    _inherit = ['snow.workflow.action.mixin']
    _description = 'approval carbon copy'
    _table = 'snow_workflow_carbon_copy'
    _order = 'id'

    wf_instance = fields.Many2one('snow.workflow.instance', string='workflow instance')
    record_id = fields.Integer(string="record id", related="wf_instance.record_id", store=False)
    object = fields.Char(string="related object", related="wf_instance.object", store=False)
    copy_user = fields.Many2one('res.users')
    object_name = fields.Char(string='object name', related='wf_instance.object_name', store=False)
    status_name = fields.Char(string="status name", related="wf_instance.status_name", store=False)
    submitter_name = fields.Char(string="submitter", related="wf_instance.initiator.name",
                                 store=False)

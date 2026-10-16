import { _t } from "@web/core/data/l10n/translation";

/**
 * 流程设计器的数据模型与 BPMN XML 之间的转换.
 *
 * 模型: { processId, nodes, flows } 表示一个作用域 (流程或子流程):
 *  - 节点 children: 子流程的 { nodes, flows }
 *  - 连线 condition: 排他网关分支的条件表达式 (Python)
 *  - 排他网关 defaultFlow: 默认分支的连线 id
 *  - 服务任务 operator: { name, parameters: [{name, expression}], resultVariable }
 *  - 脚本任务 script: Python 脚本 (仅系统管理员可编辑, 保存时在服务端检查)
 *  - 业务规则任务 decision / resultVariable: 定义中 DMN 的决策 id 与结果变量
 *  - 发送/接收消息 message: 消息名; 保存时生成 <bpmn:message> 定义
 *  - 定时器 duration: ISO 8601 时长, 如 PT1H (XML 中以字符串表达式书写)
 *  - 服务/脚本任务 loop: 多实例 { enabled, sequential, cardinality }
 *
 * 引擎约定 (workflow/attendee.py, workflow/util.py, workflow/service_operations.py):
 *  - 审批节点是 userTask, 其 name 为任务类型 (approve_execution / group_approve_execution_or / ..._and)
 *  - 每个审批节点放在一个 lane 中, lane 的 name 是审批人规则的 Python 字典字面量
 *  - 服务任务的操作写在 camunda:property serviceTaskOperator (JSON) 中
 */

/** 引擎只执行 id 为 main_process 的流程 (engines.py) */
export const MAIN_PROCESS_ID = "main_process";

export const BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL";
export const BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI";
export const DC_NS = "http://www.omg.org/spec/DD/20100524/DC";
export const DI_NS = "http://www.omg.org/spec/DD/20100524/DI";
export const CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn";

export const NODE_TYPES = {
    start: { label: _t("Start"), bpmn: "startEvent", size: [36, 36] },
    end: { label: _t("End"), bpmn: "endEvent", size: [36, 36] },
    approve_execution: { label: _t("Approve"), bpmn: "userTask", approval: true, size: [120, 60] },
    group_approve_execution_or: { label: _t("Group approve (any)"), bpmn: "userTask", approval: true, size: [120, 60] },
    group_approve_execution_and: { label: _t("Group approve (all)"), bpmn: "userTask", approval: true, size: [120, 60] },
    parallel: { label: _t("Parallel gateway"), bpmn: "parallelGateway", size: [50, 50] },
    exclusive: { label: _t("Exclusive gateway"), bpmn: "exclusiveGateway", size: [50, 50] },
    inclusive: { label: _t("Inclusive gateway"), bpmn: "inclusiveGateway", size: [50, 50] },
    event_based: { label: _t("Event-based gateway"), bpmn: "eventBasedGateway", size: [50, 50] },
    service: { label: _t("Service task"), bpmn: "serviceTask", size: [120, 60] },
    script: { label: _t("Script task"), bpmn: "scriptTask", size: [120, 60] },
    business_rule: { label: _t("Business rule task"), bpmn: "businessRuleTask", size: [120, 60] },
    send_message: { label: _t("Send message"), bpmn: "sendTask", size: [120, 60] },
    receive_message: { label: _t("Receive message"), bpmn: "receiveTask", size: [120, 60] },
    timer: { label: _t("Timer"), bpmn: "intermediateCatchEvent", size: [36, 36] },
    boundary_timer: { label: _t("Boundary timer"), bpmn: "boundaryEvent", size: [36, 36] },
    throw_event: { label: _t("Intermediate event"), bpmn: "intermediateThrowEvent", size: [36, 36] },
    call_activity: { label: _t("Call activity"), bpmn: "callActivity", size: [120, 60] },
    subprocess: { label: _t("Subprocess"), bpmn: "subProcess", size: [160, 90], container: true },
};

/** 服务任务可用的操作 (与 workflow/service_operations.py 中注册的操作保持一致) */
export const SERVICE_OPERATIONS = {
    evaluate: { label: _t("Evaluate an expression"), parameters: ["value"] },
    write_record: { label: _t("Write fields to the business record"), parameters: [] },
};

/** 定时器的形式: duration 时长 / date 日期时间 / cycle 循环 */
export const TIMER_KINDS = {
    duration: { element: "timeDuration", label: _t("Duration"), example: "PT1H" },
    date: { element: "timeDate", label: _t("Date and time"), example: "2030-01-01T09:00:00" },
    cycle: { element: "timeCycle", label: _t("Cycle"), example: "R3/PT1H" },
};

/** 审批人规则: submitter (提交人) / users (指定用户) / script (脚本返回) */
export const APPROVER_TYPES = ["submitter", "users", "script"];

/** 可以设置多实例的节点 (审批节点的多人审批由审批模型处理, 不做多实例) */
export const LOOP_TYPES = ["service", "script"];

const SCRIPT_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
/** 与 models/snow_workflow_model.py 中的 ISO_DURATION_RE 保持一致 */
const ISO_DURATION = /^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?$/;
/** 与 models/snow_workflow_model.py 中的 ISO_DATETIME_RE / ISO_CYCLE_RE 保持一致 */
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/;
const ISO_CYCLE = /^R\d*\/P(?!$)[0-9YMWDTHS.,]+$/;

const SCOPE_ELEMENTS = [
    "startEvent", "endEvent", "parallelGateway", "exclusiveGateway", "inclusiveGateway", "eventBasedGateway",
    "serviceTask", "subProcess", "scriptTask", "businessRuleTask", "sendTask", "receiveTask",
];

/** 条件网关: 分支带条件, 必须有默认分支 */
export const CONDITIONAL_GATEWAYS = ["exclusive", "inclusive"];

/** 边界定时器可以挂在这些自动节点上 (审批节点不行: 取消时无法同步审批记录) */
export const BOUNDARY_HOSTS = ["service", "script", "business_rule", "send_message", "receive_message"];

export function defaultApprover() {
    return { type: "submitter", users: [], script: "" };
}

export function defaultOperator() {
    return { name: "evaluate", parameters: [{ name: "value", expression: "" }], resultVariable: "" };
}

export function defaultLoop() {
    return { enabled: false, sequential: false, cardinality: "" };
}

/** 新建节点时各类型的专有属性 */
export function initialProps(type) {
    const props = { approver: defaultApprover() };
    if (type === "service") {
        props.operator = defaultOperator();
    }
    if (type === "script") {
        props.script = "";
    }
    if (type === "business_rule") {
        props.decision = "";
        props.resultVariable = "";
    }
    if (type === "send_message" || type === "receive_message") {
        props.message = "";
    }
    if (type === "send_message") {
        // 目标记录的表达式 (Python), 为空则消息只在本流程内被接收任务消费
        props.targetRecord = "";
    }
    if (type === "timer" || type === "boundary_timer") {
        props.timerKind = "duration";
        props.duration = "PT1H";
    }
    if (type === "boundary_timer") {
        props.attachedTo = "";
    }
    if (type === "call_activity") {
        props.calledDefinition = "";
    }
    if (LOOP_TYPES.includes(type)) {
        props.loop = defaultLoop();
    }
    return props;
}

/** 审批人规则 -> lane 的 name (Python 字典字面量) */
export function laneNameOf(approver) {
    if (approver.type === "users") {
        const ids = approver.users.map((id) => Number(id)).join(", ");
        return `{'user': {'domain': [('id', 'in', [${ids}])]}}`;
    }
    if (approver.type === "script") {
        return `{'script': {'key': '${approver.script}'}}`;
    }
    return "{'user': 'submitter'}";
}

/** lane 的 name -> 审批人规则, 无法识别时返回提交人 */
export function approverOfLaneName(name) {
    const text = name || "";
    if (text.includes("'script'")) {
        const match = text.match(/'key':\s*'([^']*)'/);
        return { type: "script", users: [], script: match ? match[1] : "" };
    }
    if (text.includes("'domain'")) {
        const match = text.match(/\('id',\s*'in',\s*\[([\d,\s]*)\]\)/);
        const users = match ? match[1].split(",").map((s) => s.trim()).filter(Boolean).map(Number) : [];
        return { type: "users", users, script: "" };
    }
    return defaultApprover();
}

/** 服务任务的操作 -> camunda:property 的 JSON */
export function operatorJson(operator) {
    const parameters = {};
    for (const param of operator.parameters) {
        parameters[param.name] = { value: param.expression };
    }
    const json = { name: operator.name, parameters };
    if (operator.resultVariable) {
        json.resultVariable = operator.resultVariable;
    }
    return JSON.stringify(json);
}

function operatorOfJson(text) {
    let json = null;
    try {
        json = JSON.parse(text || "null");
    } catch {
        json = null;
    }
    if (!json || typeof json !== "object") {
        return defaultOperator();
    }
    return {
        name: json.name || "",
        parameters: Object.entries(json.parameters || {}).map(([name, param]) => ({
            name,
            expression: param?.value ?? "",
        })),
        resultVariable: json.resultVariable || "",
    };
}

/** 消息的 BPMN id: 由消息名生成, 同一名字总是得到同一个 id */
export function messageId(name) {
    return `Message_${name.replace(/[^A-Za-z0-9_]/g, "_")}`;
}

/** 定时器时长去掉引号后的文本 (XML 中为 'PT1H') */
function durationOfText(text) {
    return (text || "").trim().replace(/^'(.*)'$/, "$1");
}

function sizeOf(node) {
    return NODE_TYPES[node.type].size;
}

/** 所有作用域中的节点 (包括子流程中的), 用于收集消息等 */
function allNodes(scope, out = []) {
    for (const node of scope.nodes) {
        out.push(node);
        if (node.type === "subprocess") {
            allNodes(node.children, out);
        }
    }
    return out;
}

/** 校验一个作用域 (流程或子流程), 返回错误信息 */
function validateScope(scope, errors, decisions) {
    const starts = scope.nodes.filter((n) => n.type === "start");
    const ends = scope.nodes.filter((n) => n.type === "end");
    if (starts.length !== 1) {
        errors.push(_t("The process needs exactly one start event."));
    }
    if (ends.length < 1) {
        errors.push(_t("The process needs at least one end event."));
    }
    for (const node of scope.nodes) {
        const label = node.name || NODE_TYPES[node.type].label;
        const incoming = scope.flows.filter((f) => f.target === node.id);
        const outgoing = scope.flows.filter((f) => f.source === node.id);
        if (node.type !== "start" && node.type !== "boundary_timer" && !incoming.length) {
            errors.push(_t("“%s” has no incoming flow.", label));
        }
        if (node.type === "call_activity" && !node.calledDefinition) {
            errors.push(_t("Choose the process that “%s” calls.", label));
        }
        if (node.type === "boundary_timer") {
            const host = scope.nodes.find((n) => n.id === node.attachedTo);
            if (!host || !BOUNDARY_HOSTS.includes(host.type)) {
                errors.push(_t("The boundary timer “%s” must be attached to a service, script, business rule, send or receive task.", label));
            }
        }
        if (node.type !== "end" && !outgoing.length) {
            errors.push(_t("“%s” has no outgoing flow.", label));
        }
        if (!["exclusive", "parallel"].includes(node.type) && outgoing.length > 1) {
            errors.push(_t("“%s” can have only one outgoing flow; use a gateway to split the flow.", label));
        }
        if (NODE_TYPES[node.type].approval) {
            if (node.approver.type === "users" && !node.approver.users.length) {
                errors.push(_t("Choose the approvers of “%s”.", label));
            }
            if (node.approver.type === "script" && !SCRIPT_KEY.test(node.approver.script)) {
                errors.push(_t("The script key of “%s” is not valid.", label));
            }
        }
        if (node.type === "event_based") {
            if (outgoing.length < 2) {
                errors.push(_t("The event-based gateway “%s” needs at least two outgoing flows.", label));
            }
            for (const flow of outgoing) {
                const target = scope.nodes.find((n) => n.id === flow.target);
                if (!["receive_message", "timer"].includes(target?.type)) {
                    errors.push(_t("After the event-based gateway “%s” only receive tasks and timers are allowed.", label));
                }
            }
        }
        if (CONDITIONAL_GATEWAYS.includes(node.type)) {
            if (!outgoing.some((f) => f.id === node.defaultFlow)) {
                errors.push(_t("“%s” needs a default flow.", label));
            }
            for (const flow of outgoing) {
                if (flow.id !== node.defaultFlow && !(flow.condition || "").trim()) {
                    errors.push(_t("The flow of “%s” needs a condition.", label));
                }
            }
        }
        if (node.type === "service") {
            const op = node.operator;
            if (!SERVICE_OPERATIONS[op.name]) {
                errors.push(_t("Choose an operation for “%s”.", label));
            }
            if (op.name === "evaluate" && !op.parameters.some((p) => p.name === "value")) {
                errors.push(_t("The operation of “%s” needs a value.", label));
            }
            for (const param of op.parameters) {
                if (!param.expression.trim()) {
                    errors.push(_t("The parameter “%s” of “%s” needs an expression.", param.name, label));
                }
            }
            if (op.resultVariable && !IDENTIFIER.test(op.resultVariable)) {
                errors.push(_t("The result variable of “%s” must be a valid name.", label));
            }
        }
        if (node.type === "script" && !(node.script || "").trim()) {
            errors.push(_t("The script task “%s” needs a script.", label));
        }
        if (node.type === "business_rule") {
            if (!node.decision) {
                errors.push(_t("Choose the decision of “%s”.", label));
            } else if (decisions && !decisions.includes(node.decision)) {
                errors.push(_t("The decision “%(decision)s” of “%(task)s” is not defined in the DMN decisions.",
                    { decision: node.decision, task: label }));
            }
            if (node.resultVariable && !IDENTIFIER.test(node.resultVariable)) {
                errors.push(_t("The result variable of “%s” must be a valid name.", label));
            }
        }
        if (node.type === "send_message" || node.type === "receive_message") {
            if (!(node.message || "").trim()) {
                errors.push(_t("The message task “%s” needs a message name.", label));
            }
        }
        if (node.type === "timer" || node.type === "boundary_timer") {
            const kind = TIMER_KINDS[node.timerKind] || TIMER_KINDS.duration;
            const valid = {
                duration: ISO_DURATION,
                date: ISO_DATETIME,
                cycle: ISO_CYCLE,
            }[node.timerKind || "duration"];
            if (!valid.test(node.duration || "")) {
                errors.push(_t("The time of “%(task)s” is not valid, e.g. %(example)s.",
                    { task: label, example: kind.example }));
            }
        }
        if (LOOP_TYPES.includes(node.type) && node.loop?.enabled && !(node.loop.cardinality || "").trim()) {
            errors.push(_t("The multi-instance task “%s” needs a cardinality.", label));
        }
        if (node.type === "subprocess") {
            validateScope(node.children, errors, decisions);
        }
    }
}

/**
 * 校验设计结果, 返回错误信息列表 (空表示可以保存)
 * @param {Object} model
 * @param {string[]} unsupported 载入时发现的不支持元素
 * @param {string[]|null} decisions 定义中 DMN 的决策 id (null 表示不检查)
 */
export function validateModel(model, unsupported = [], decisions = null) {
    const errors = unsupported.map((name) => _t("The element “%s” is not supported by the designer yet.", name));
    validateScope(model, errors, decisions);
    const messageIds = {};
    for (const node of allNodes(model)) {
        if (node.type !== "send_message" && node.type !== "receive_message") {
            continue;
        }
        const name = (node.message || "").trim();
        if (!name) {
            continue;
        }
        const id = messageId(name);
        if (messageIds[id] && messageIds[id] !== name) {
            errors.push(_t("The messages “%(first)s” and “%(second)s” cannot be told apart, rename one of them.",
                { first: messageIds[id], second: name }));
        }
        messageIds[id] = name;
    }
    return errors;
}

function escapeXml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/** 所有审批节点 (包括子流程中的), 用于生成 lane */
function allApprovals(scope, out = []) {
    for (const node of scope.nodes) {
        if (NODE_TYPES[node.type].approval) {
            out.push(node);
        }
        if (node.type === "subprocess") {
            allApprovals(node.children, out);
        }
    }
    return out;
}

/** 多实例子元素 */
function loopXml(node, pad) {
    if (!LOOP_TYPES.includes(node.type) || !node.loop?.enabled) {
        return [];
    }
    const sequential = node.loop.sequential ? "true" : "false";
    return [
        `${pad}  <bpmn:multiInstanceLoopCharacteristics isSequential="${sequential}">` +
        `<bpmn:loopCardinality>${escapeXml(node.loop.cardinality.trim())}</bpmn:loopCardinality>` +
        "</bpmn:multiInstanceLoopCharacteristics>",
    ];
}

function scopeXml(scope, indent, lines) {
    const byId = Object.fromEntries(scope.nodes.map((n) => [n.id, n]));
    for (const node of scope.nodes) {
        const info = NODE_TYPES[node.type];
        const pad = " ".repeat(indent);
        const attrs = [`id="${escapeXml(node.id)}"`];
        if (info.approval) {
            attrs.push(`name="${escapeXml(node.type)}"`);
        } else if (node.type === "service" || node.name) {
            attrs.push(`name="${escapeXml(node.name || info.label)}"`);
        }
        if (CONDITIONAL_GATEWAYS.includes(node.type) && node.defaultFlow) {
            attrs.push(`default="${escapeXml(node.defaultFlow)}"`);
        }
        if (node.type === "business_rule") {
            attrs.push(`camunda:decisionRef="${escapeXml(node.decision)}"`);
            if (node.resultVariable) {
                attrs.push(`camunda:resultVariable="${escapeXml(node.resultVariable)}"`);
            }
        }
        if (node.type === "send_message" || node.type === "receive_message") {
            attrs.push(`messageRef="${escapeXml(messageId(node.message.trim()))}"`);
        }
        const children = [];
        if (info.approval && node.name) {
            // 审批节点的 name 是任务类型, 设计器中的名称写入 documentation
            children.push(`${pad}  <bpmn:documentation>${escapeXml(node.name)}</bpmn:documentation>`);
        }
        if (node.type === "service") {
            children.push(`${pad}  <bpmn:extensionElements><camunda:properties>` +
                `<camunda:property name="serviceTaskOperator" value="${escapeXml(operatorJson(node.operator))}"/>` +
                "</camunda:properties></bpmn:extensionElements>");
        }
        if (node.type === "send_message" && (node.targetRecord || "").trim()) {
            children.push(`${pad}  <bpmn:extensionElements><camunda:properties>` +
                `<camunda:property name="targetRecord" value="${escapeXml(node.targetRecord.trim())}"/>` +
                "</camunda:properties></bpmn:extensionElements>");
        }
        if (node.type === "script") {
            children.push(`${pad}  <bpmn:script>${escapeXml(node.script.trim())}</bpmn:script>`);
        }
        children.push(...loopXml(node, pad));
        if (node.type === "boundary_timer") {
            attrs.push(`attachedToRef="${escapeXml(node.attachedTo)}"`);
        }
        if (node.type === "call_activity") {
            attrs.push(`calledElement="call_${escapeXml(node.calledDefinition)}"`);
        }
        if (node.type === "timer" || node.type === "boundary_timer") {
            const element = (TIMER_KINDS[node.timerKind] || TIMER_KINDS.duration).element;
            children.push(`${pad}  <bpmn:timerEventDefinition><bpmn:${element}>` +
                `'${escapeXml(node.duration.trim())}'</bpmn:${element}></bpmn:timerEventDefinition>`);
        }
        for (const flow of scope.flows.filter((f) => f.target === node.id)) {
            children.push(`${pad}  <bpmn:incoming>${escapeXml(flow.id)}</bpmn:incoming>`);
        }
        for (const flow of scope.flows.filter((f) => f.source === node.id)) {
            children.push(`${pad}  <bpmn:outgoing>${escapeXml(flow.id)}</bpmn:outgoing>`);
        }
        if (node.type === "subprocess") {
            lines.push(`${pad}<bpmn:${info.bpmn} ${attrs.join(" ")}>`);
            lines.push(...children);
            scopeXml(node.children, indent + 2, lines);
            lines.push(`${pad}</bpmn:${info.bpmn}>`);
        } else if (children.length) {
            lines.push(`${pad}<bpmn:${info.bpmn} ${attrs.join(" ")}>`);
            lines.push(...children);
            lines.push(`${pad}</bpmn:${info.bpmn}>`);
        } else {
            lines.push(`${pad}<bpmn:${info.bpmn} ${attrs.join(" ")}/>`);
        }
    }
    for (const flow of scope.flows) {
        if (!byId[flow.source] || !byId[flow.target]) {
            continue;
        }
        const pad = " ".repeat(indent);
        const attrs = `id="${escapeXml(flow.id)}" sourceRef="${escapeXml(flow.source)}" targetRef="${escapeXml(flow.target)}"`;
        if (flow.condition && flow.condition.trim()) {
            lines.push(`${pad}<bpmn:sequenceFlow ${attrs}>` +
                `<bpmn:conditionExpression>${escapeXml(flow.condition.trim())}</bpmn:conditionExpression>` +
                "</bpmn:sequenceFlow>");
        } else {
            lines.push(`${pad}<bpmn:sequenceFlow ${attrs}/>`);
        }
    }
}

function diagramXml(scope, lines) {
    const byId = Object.fromEntries(scope.nodes.map((n) => [n.id, n]));
    for (const node of scope.nodes) {
        const [w, h] = sizeOf(node);
        lines.push(`      <bpmndi:BPMNShape id="${escapeXml(node.id)}_di" bpmnElement="${escapeXml(node.id)}">` +
            `<dc:Bounds x="${node.x}" y="${node.y}" width="${w}" height="${h}"/></bpmndi:BPMNShape>`);
        if (node.type === "subprocess") {
            diagramXml(node.children, lines);
        }
    }
    for (const flow of scope.flows) {
        const source = byId[flow.source];
        const target = byId[flow.target];
        if (!source || !target) {
            continue;
        }
        const [sw, sh] = sizeOf(source);
        const [, th] = sizeOf(target);
        lines.push(`      <bpmndi:BPMNEdge id="${escapeXml(flow.id)}_di" bpmnElement="${escapeXml(flow.id)}">` +
            `<di:waypoint x="${source.x + sw}" y="${source.y + sh / 2}"/>` +
            `<di:waypoint x="${target.x}" y="${target.y + th / 2}"/></bpmndi:BPMNEdge>`);
    }
}

/**
 * 设计模型 -> BPMN XML (包含 lane, 消息定义, 子流程, 服务任务与 BPMNDiagram 坐标)
 */
export function toBpmnXml(model) {
    const lines = [];
    lines.push('<?xml version="1.0" encoding="UTF-8"?>');
    lines.push(`<bpmn:definitions xmlns:bpmn="${BPMN_NS}" xmlns:bpmndi="${BPMNDI_NS}" ` +
        `xmlns:dc="${DC_NS}" xmlns:di="${DI_NS}" xmlns:camunda="${CAMUNDA_NS}" ` +
        `id="Definitions_${escapeXml(model.processId)}" targetNamespace="http://snow.workflow/bpmn">`);

    // 消息定义: 发送/接收任务引用的消息名 (同名只生成一次)
    const messages = {};
    for (const node of allNodes(model)) {
        if ((node.type === "send_message" || node.type === "receive_message") && node.message.trim()) {
            messages[messageId(node.message.trim())] = node.message.trim();
        }
    }
    for (const [id, name] of Object.entries(messages)) {
        lines.push(`  <bpmn:message id="${escapeXml(id)}" name="${escapeXml(name)}"/>`);
    }

    lines.push(`  <bpmn:process id="${escapeXml(model.processId)}" isExecutable="true">`);

    const approvals = allApprovals(model);
    if (approvals.length) {
        lines.push('    <bpmn:laneSet id="LaneSet_1">');
        for (const node of approvals) {
            lines.push(`      <bpmn:lane id="Lane_${escapeXml(node.id)}" name="${escapeXml(laneNameOf(node.approver))}">`);
            lines.push(`        <bpmn:flowNodeRef>${escapeXml(node.id)}</bpmn:flowNodeRef>`);
            lines.push("      </bpmn:lane>");
        }
        lines.push("    </bpmn:laneSet>");
    }
    scopeXml(model, 4, lines);
    lines.push("  </bpmn:process>");

    lines.push('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">');
    lines.push(`    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${escapeXml(model.processId)}">`);
    diagramXml(model, lines);
    lines.push("    </bpmndi:BPMNPlane>");
    lines.push("  </bpmndi:BPMNDiagram>");
    lines.push("</bpmn:definitions>");
    return lines.join("\n");
}

function localName(el) {
    return el.localName || el.nodeName.split(":").pop();
}

function childrenNamed(el, name) {
    return [...el.children].filter((c) => localName(c) === name);
}

function descendantsNamed(root, name) {
    return [...root.getElementsByTagName("*")].filter((el) => localName(el) === name);
}

/** 读取带命名空间的属性 (camunda:decisionRef 等) */
function camundaAttr(el, name) {
    return el.getAttributeNS(CAMUNDA_NS, name) || "";
}

function loopOf(el) {
    const loop = childrenNamed(el, "multiInstanceLoopCharacteristics")[0];
    if (!loop) {
        return defaultLoop();
    }
    return {
        enabled: true,
        sequential: loop.getAttribute("isSequential") === "true",
        cardinality: childrenNamed(loop, "loopCardinality")[0]?.textContent || "",
    };
}

/** DMN 文本中的决策 id; 无法解析时返回空列表 */
export function decisionIdsOfDmn(dmnXml) {
    if (!dmnXml) {
        return [];
    }
    const doc = new DOMParser().parseFromString(dmnXml, "text/xml");
    if (doc.getElementsByTagName("parsererror").length) {
        return [];
    }
    return descendantsNamed(doc, "decision").map((el) => el.getAttribute("id")).filter(Boolean);
}

/**
 * BPMN XML -> 设计模型. 不支持的元素收集在 unsupported 中 (保存时同样会被拒绝).
 */
export function fromBpmnXml(xml) {
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    if (doc.getElementsByTagName("parsererror").length) {
        throw new Error("invalid xml");
    }
    const process = descendantsNamed(doc, "process")[0];
    const bounds = {};
    for (const shape of descendantsNamed(doc, "BPMNShape")) {
        const dc = descendantsNamed(shape, "Bounds")[0];
        if (dc) {
            bounds[shape.getAttribute("bpmnElement")] = [Number(dc.getAttribute("x")), Number(dc.getAttribute("y"))];
        }
    }
    const laneOf = {};
    for (const lane of descendantsNamed(doc, "lane")) {
        const approver = approverOfLaneName(lane.getAttribute("name"));
        for (const ref of descendantsNamed(lane, "flowNodeRef")) {
            laneOf[ref.textContent] = approver;
        }
    }
    const messageNames = {};
    for (const message of descendantsNamed(doc, "message")) {
        messageNames[message.getAttribute("id")] = message.getAttribute("name") || "";
    }

    const unsupported = [];
    let index = 0;
    function parseScope(scopeEl) {
        const nodes = [];
        const flows = [];
        for (const el of [...scopeEl.children]) {
            const bpmn = localName(el);
            if (bpmn === "sequenceFlow") {
                const condition = childrenNamed(el, "conditionExpression")[0];
                flows.push({
                    id: el.getAttribute("id"),
                    source: el.getAttribute("sourceRef"),
                    target: el.getAttribute("targetRef"),
                    condition: condition ? condition.textContent : "",
                });
                continue;
            }
            if (["laneSet", "documentation", "extensionElements", "incoming", "outgoing"].includes(bpmn)) {
                continue;
            }
            let type = null;
            if (bpmn === "userTask") {
                if (NODE_TYPES[el.getAttribute("name")]?.approval) {
                    type = el.getAttribute("name");
                } else {
                    unsupported.push(`userTask (${el.getAttribute("name") || ""})`);
                    continue;
                }
            } else if (["intermediateCatchEvent", "boundaryEvent"].includes(bpmn)
                && childrenNamed(el, "timerEventDefinition").length) {
                type = bpmn === "boundaryEvent" ? "boundary_timer" : "timer";
            } else if (bpmn === "callActivity") {
                type = "call_activity";
            } else if (bpmn === "intermediateThrowEvent" && !childrenNamed(el, "messageEventDefinition").length
                && !childrenNamed(el, "signalEventDefinition").length) {
                type = "throw_event";
            } else if (SCOPE_ELEMENTS.includes(bpmn)) {
                type = {
                    startEvent: "start",
                    endEvent: "end",
                    parallelGateway: "parallel",
                    exclusiveGateway: "exclusive",
                    inclusiveGateway: "inclusive",
                    eventBasedGateway: "event_based",
                    serviceTask: "service",
                    subProcess: "subprocess",
                    scriptTask: "script",
                    businessRuleTask: "business_rule",
                    sendTask: "send_message",
                    receiveTask: "receive_message",
                }[bpmn];
            } else {
                unsupported.push(bpmn);
                continue;
            }
            const id = el.getAttribute("id");
            const [x, y] = bounds[id] || [60 + index * 160, 120];
            index += 1;
            const node = { id, type, name: "", x, y, approver: defaultApprover() };
            if (NODE_TYPES[type].approval) {
                node.approver = laneOf[id] || defaultApprover();
                node.name = childrenNamed(el, "documentation")[0]?.textContent || "";
            } else if (type === "service") {
                const property = descendantsNamed(el, "property")
                    .find((p) => p.getAttribute("name") === "serviceTaskOperator");
                node.operator = operatorOfJson(property?.getAttribute("value"));
                node.name = el.getAttribute("name") || "";
                node.loop = loopOf(el);
            } else if (type === "script") {
                node.script = childrenNamed(el, "script")[0]?.textContent || "";
                node.name = el.getAttribute("name") || "";
                node.loop = loopOf(el);
            } else if (type === "business_rule") {
                node.decision = camundaAttr(el, "decisionRef");
                node.resultVariable = camundaAttr(el, "resultVariable");
                node.name = el.getAttribute("name") || "";
            } else if (type === "call_activity") {
                node.calledDefinition = (el.getAttribute("calledElement") || "").replace(/^call_/, "");
                node.name = el.getAttribute("name") || "";
            } else if (type === "send_message" || type === "receive_message") {
                node.message = messageNames[el.getAttribute("messageRef")] || "";
                node.name = el.getAttribute("name") || "";
                if (type === "send_message") {
                    const property = descendantsNamed(el, "property")
                        .find((p) => p.getAttribute("name") === "targetRecord");
                    node.targetRecord = property?.getAttribute("value") || "";
                }
            } else if (type === "timer" || type === "boundary_timer") {
                if (type === "boundary_timer") {
                    node.attachedTo = el.getAttribute("attachedToRef") || "";
                }
                // 时间元素决定定时器的形式 (时长 / 日期 / 循环)
                const definition = childrenNamed(el, "timerEventDefinition")[0];
                const timerKind = Object.entries(TIMER_KINDS).find(
                    ([, info]) => childrenNamed(definition, info.element).length
                )?.[0] || "duration";
                const time = childrenNamed(definition, TIMER_KINDS[timerKind].element)[0];
                node.timerKind = timerKind;
                node.duration = durationOfText(time?.textContent);
                node.name = el.getAttribute("name") || "";
            } else if (CONDITIONAL_GATEWAYS.includes(type)) {
                node.defaultFlow = el.getAttribute("default") || "";
                node.name = el.getAttribute("name") || "";
            } else if (type === "subprocess") {
                node.name = el.getAttribute("name") || "";
                node.children = parseScope(el);
            } else {
                node.name = el.getAttribute("name") || "";
            }
            nodes.push(node);
        }
        const ids = new Set(nodes.map((n) => n.id));
        return {
            nodes,
            flows: flows.filter((f) => ids.has(f.source) && ids.has(f.target)),
        };
    }

    const scope = parseScope(process || doc.documentElement);
    return { processId: MAIN_PROCESS_ID, ...scope, unsupported };
}

/** 生成不与已有元素冲突的 id (BPMN 的 id 须以字母开头) */
export function newId(prefix) {
    return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 整理一个作用域 (流程或子流程) 的布局: 按流程顺序从左到右分列 (列 = 最长路径层数),
 * 同一列的节点上下排开并居中对齐, 单个节点的列落在同一条中线上; 边界定时器放在所挂接节点的正下方.
 * 环路只影响分列时忽略回边, 不改变连线. 返回 节点 id -> {x, y}.
 */
export function layoutScope(scope) {
    const LEFT = 60;
    const TOP = 60;
    const COLUMN_GAP = 140;
    const ROW_GAP = 64;
    const GRID = 10;
    const snap = (value) => Math.max(0, Math.round(value / GRID) * GRID);
    const sizeOf = (node) => NODE_TYPES[node.type].size;

    const main = scope.nodes.filter((n) => n.type !== "boundary_timer");
    const boundaries = scope.nodes.filter((n) => n.type === "boundary_timer");
    const ids = new Set(main.map((n) => n.id));
    const edges = scope.flows.filter((f) => ids.has(f.source) && ids.has(f.target) && f.source !== f.target);
    const outgoing = Object.fromEntries(main.map((n) => [n.id, []]));
    const incomingCount = Object.fromEntries(main.map((n) => [n.id, 0]));
    for (const edge of edges) {
        outgoing[edge.source].push(edge.target);
        incomingCount[edge.target] += 1;
    }

    // 去掉回边: 深度优先搜索时, 指向仍在栈上的节点的边视为回边
    const acyclic = Object.fromEntries(main.map((n) => [n.id, []]));
    const state = {};
    const visit = (id) => {
        state[id] = "open";
        for (const target of outgoing[id]) {
            if (state[target] === "open") {
                continue;
            }
            acyclic[id].push(target);
            if (!state[target]) {
                visit(target);
            }
        }
        state[id] = "done";
    };
    // 从没有入线的节点开始, 保证开始事件在最左边
    const starts = main.filter((n) => incomingCount[n.id] === 0);
    for (const node of [...starts, ...main]) {
        if (!state[node.id]) {
            visit(node.id);
        }
    }

    // 列 = 无环图中从起点出发的最长路径
    const layer = Object.fromEntries(main.map((n) => [n.id, 0]));
    for (let pass = 0; pass < main.length; pass++) {
        for (const id of Object.keys(acyclic)) {
            for (const target of acyclic[id]) {
                layer[target] = Math.max(layer[target], layer[id] + 1);
            }
        }
    }

    // 每列内的顺序: 按前驱节点在上一列中的平均位置排序, 减少交叉
    const byLayer = [];
    for (const node of main) {
        (byLayer[layer[node.id]] ||= []).push(node);
    }
    const columns = byLayer.filter((column) => column && column.length);
    const position = {};
    columns.forEach((column, index) => {
        if (index > 0) {
            const previous = columns[index - 1];
            const rank = Object.fromEntries(previous.map((n, i) => [n.id, i]));
            const original = Object.fromEntries(column.map((n, i) => [n.id, i]));
            // 没有前驱的节点排在最后, 保持原来的相对顺序
            const barycenter = (node) => {
                const preds = previous.filter((p) => acyclic[p.id].includes(node.id)).map((p) => rank[p.id]);
                return preds.length ? preds.reduce((a, b) => a + b, 0) / preds.length : 1e9 + original[node.id];
            };
            column.sort((a, b) => barycenter(a) - barycenter(b));
        }
    });

    // 所有列共用一条中线, 列宽由最宽的节点决定
    const heights = columns.map((column) =>
        column.reduce((sum, n) => sum + sizeOf(n)[1], 0) + ROW_GAP * Math.max(0, column.length - 1));
    const centerY = TOP + Math.max(0, ...heights) / 2;
    let columnX = LEFT;
    columns.forEach((column, index) => {
        const width = Math.max(...column.map((n) => sizeOf(n)[0]));
        let y = centerY - heights[index] / 2;
        for (const node of column) {
            const [w, h] = sizeOf(node);
            position[node.id] = { x: snap(columnX + (width - w) / 2), y: snap(y) };
            y += h + ROW_GAP;
        }
        columnX += width + COLUMN_GAP;
    });

    // 边界定时器: 在所挂接节点的正下方居中
    for (const node of boundaries) {
        const host = main.find((n) => n.id === node.attachedTo);
        if (!host) {
            position[node.id] = { x: node.x, y: node.y };
            continue;
        }
        const [hostW, hostH] = sizeOf(host);
        const [w] = sizeOf(node);
        position[node.id] = {
            x: snap(position[host.id].x + (hostW - w) / 2),
            y: snap(position[host.id].y + hostH + 16),
        };
    }
    return position;
}

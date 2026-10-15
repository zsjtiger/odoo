import { _t } from "@web/core/data/l10n/translation";

/**
 * 流程设计器的数据模型与 BPMN XML 之间的转换.
 *
 * 引擎约定 (workflow/attendee.py, workflow/util.py):
 *  - 审批节点是 userTask, 其 name 为任务类型 (approve_execution / group_approve_execution_or / ..._and)
 *  - 每个审批节点放在一个 lane 中, lane 的 name 是审批人规则的 Python 字典字面量
 */

/** 引擎只执行 id 为 main_process 的流程 (engines.py) */
export const MAIN_PROCESS_ID = "main_process";

export const BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL";
export const BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI";
export const DC_NS = "http://www.omg.org/spec/DD/20100524/DC";
export const DI_NS = "http://www.omg.org/spec/DD/20100524/DI";

export const NODE_TYPES = {
    start: { label: _t("Start"), bpmn: "startEvent", size: [36, 36] },
    end: { label: _t("End"), bpmn: "endEvent", size: [36, 36] },
    approve_execution: { label: _t("Approve"), bpmn: "userTask", approval: true, size: [120, 60] },
    group_approve_execution_or: { label: _t("Group approve (any)"), bpmn: "userTask", approval: true, size: [120, 60] },
    group_approve_execution_and: { label: _t("Group approve (all)"), bpmn: "userTask", approval: true, size: [120, 60] },
    parallel: { label: _t("Parallel gateway"), bpmn: "parallelGateway", size: [50, 50] },
    exclusive: { label: _t("Exclusive gateway"), bpmn: "exclusiveGateway", size: [50, 50] },
};

const BPMN_TO_TYPE = {
    startEvent: "start",
    endEvent: "end",
    parallelGateway: "parallel",
    exclusiveGateway: "exclusive",
};

/** 审批人规则: submitter (提交人) / users (指定用户) / script (脚本返回) */
export const APPROVER_TYPES = ["submitter", "users", "script"];

export function defaultApprover() {
    return { type: "submitter", users: [], script: "" };
}

const SCRIPT_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

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

/** 校验设计结果, 返回错误信息列表 (空表示可以保存) */
export function validateModel(model) {
    const errors = [];
    const starts = model.nodes.filter((n) => n.type === "start");
    const ends = model.nodes.filter((n) => n.type === "end");
    if (starts.length !== 1) {
        errors.push(_t("The process needs exactly one start event."));
    }
    if (ends.length < 1) {
        errors.push(_t("The process needs at least one end event."));
    }
    for (const node of model.nodes) {
        if (NODE_TYPES[node.type]?.approval) {
            if (node.approver.type === "users" && !node.approver.users.length) {
                errors.push(_t("Choose the approvers of “%s”.", node.name || NODE_TYPES[node.type].label));
            }
            if (node.approver.type === "script" && !SCRIPT_KEY.test(node.approver.script)) {
                errors.push(_t("The script key of “%s” is not valid.", node.name || NODE_TYPES[node.type].label));
            }
        }
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

function centerRight(node) {
    const [w, h] = NODE_TYPES[node.type].size;
    return [node.x + w, node.y + h / 2];
}

function centerLeft(node) {
    const [, h] = NODE_TYPES[node.type].size;
    return [node.x, node.y + h / 2];
}

/**
 * 设计模型 -> BPMN XML (包含 lane 与 BPMNDiagram 坐标, 设计器重新打开时可以还原布局)
 */
export function toBpmnXml(model) {
    const { processId, nodes, flows } = model;
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const outgoing = (id) => flows.filter((f) => f.source === id);
    const incoming = (id) => flows.filter((f) => f.target === id);
    const lines = [];
    lines.push('<?xml version="1.0" encoding="UTF-8"?>');
    lines.push(`<bpmn:definitions xmlns:bpmn="${BPMN_NS}" xmlns:bpmndi="${BPMNDI_NS}" ` +
        `xmlns:dc="${DC_NS}" xmlns:di="${DI_NS}" id="Definitions_${escapeXml(processId)}" ` +
        'targetNamespace="http://snow.workflow/bpmn">');
    lines.push(`  <bpmn:process id="${escapeXml(processId)}" isExecutable="true">`);

    const approvals = nodes.filter((n) => NODE_TYPES[n.type].approval);
    if (approvals.length) {
        lines.push('    <bpmn:laneSet id="LaneSet_1">');
        for (const node of approvals) {
            lines.push(`      <bpmn:lane id="Lane_${escapeXml(node.id)}" name="${escapeXml(laneNameOf(node.approver))}">`);
            lines.push(`        <bpmn:flowNodeRef>${escapeXml(node.id)}</bpmn:flowNodeRef>`);
            lines.push("      </bpmn:lane>");
        }
        lines.push("    </bpmn:laneSet>");
    }

    for (const node of nodes) {
        const info = NODE_TYPES[node.type];
        const attrs = [`id="${escapeXml(node.id)}"`];
        if (info.approval) {
            attrs.push(`name="${escapeXml(node.type)}"`);
        } else if (node.name) {
            attrs.push(`name="${escapeXml(node.name)}"`);
        }
        // 审批节点的 name 是任务类型, 设计器中的名称写入 documentation
        const children = [
            ...(info.approval && node.name ? [`        <bpmn:documentation>${escapeXml(node.name)}</bpmn:documentation>`] : []),
            ...incoming(node.id).map((f) => `        <bpmn:incoming>${escapeXml(f.id)}</bpmn:incoming>`),
            ...outgoing(node.id).map((f) => `        <bpmn:outgoing>${escapeXml(f.id)}</bpmn:outgoing>`),
        ];
        if (children.length) {
            lines.push(`    <bpmn:${info.bpmn} ${attrs.join(" ")}>`);
            lines.push(...children);
            lines.push(`    </bpmn:${info.bpmn}>`);
        } else {
            lines.push(`    <bpmn:${info.bpmn} ${attrs.join(" ")}/>`);
        }
    }

    for (const flow of flows) {
        lines.push(`    <bpmn:sequenceFlow id="${escapeXml(flow.id)}" sourceRef="${escapeXml(flow.source)}" ` +
            `targetRef="${escapeXml(flow.target)}"/>`);
    }
    lines.push("  </bpmn:process>");

    lines.push("  <bpmndi:BPMNDiagram id=\"BPMNDiagram_1\">");
    lines.push(`    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${escapeXml(processId)}">`);
    for (const node of nodes) {
        const [w, h] = NODE_TYPES[node.type].size;
        lines.push(`      <bpmndi:BPMNShape id="${escapeXml(node.id)}_di" bpmnElement="${escapeXml(node.id)}">` +
            `<dc:Bounds x="${node.x}" y="${node.y}" width="${w}" height="${h}"/></bpmndi:BPMNShape>`);
    }
    for (const flow of flows) {
        const [x1, y1] = centerRight(byId[flow.source]);
        const [x2, y2] = centerLeft(byId[flow.target]);
        lines.push(`      <bpmndi:BPMNEdge id="${escapeXml(flow.id)}_di" bpmnElement="${escapeXml(flow.id)}">` +
            `<di:waypoint x="${x1}" y="${y1}"/><di:waypoint x="${x2}" y="${y2}"/></bpmndi:BPMNEdge>`);
    }
    lines.push("    </bpmndi:BPMNPlane>");
    lines.push("  </bpmndi:BPMNDiagram>");
    lines.push("</bpmn:definitions>");
    return lines.join("\n");
}

function localName(el) {
    return el.localName || el.nodeName.split(":").pop();
}

function elementsNamed(root, name) {
    return [...root.getElementsByTagName("*")].filter((el) => localName(el) === name);
}

/**
 * BPMN XML -> 设计模型. 不认识的元素 (如 serviceTask) 会被忽略.
 */
export function fromBpmnXml(xml, { defaultProcessId = MAIN_PROCESS_ID } = {}) {
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    if (doc.getElementsByTagName("parsererror").length) {
        throw new Error("invalid xml");
    }
    const process = elementsNamed(doc, "process")[0];
    const processId = MAIN_PROCESS_ID || defaultProcessId;

    const bounds = {};
    for (const shape of elementsNamed(doc, "BPMNShape")) {
        const dc = elementsNamed(shape, "Bounds")[0];
        if (dc) {
            bounds[shape.getAttribute("bpmnElement")] = [Number(dc.getAttribute("x")), Number(dc.getAttribute("y"))];
        }
    }

    const laneOf = {};
    for (const lane of elementsNamed(doc, "lane")) {
        const approver = approverOfLaneName(lane.getAttribute("name"));
        for (const ref of elementsNamed(lane, "flowNodeRef")) {
            laneOf[ref.textContent] = approver;
        }
    }

    const nodes = [];
    let index = 0;
    for (const el of [...doc.getElementsByTagName("*")]) {
        const bpmn = localName(el);
        let type = BPMN_TO_TYPE[bpmn];
        if (bpmn === "userTask") {
            type = el.getAttribute("name");
            if (!NODE_TYPES[type]?.approval) {
                continue;
            }
        }
        if (!type) {
            continue;
        }
        const id = el.getAttribute("id");
        const [x, y] = bounds[id] || [60 + index * 160, 120];
        index += 1;
        const node = { id, type, name: "", x, y, approver: defaultApprover() };
        if (NODE_TYPES[type].approval) {
            node.approver = laneOf[id] || defaultApprover();
            node.name = elementsNamed(el, "documentation")[0]?.textContent || "";
        } else {
            node.name = el.getAttribute("name") || "";
        }
        nodes.push(node);
    }

    const ids = new Set(nodes.map((n) => n.id));
    const flows = elementsNamed(doc, "sequenceFlow")
        .map((el) => ({ id: el.getAttribute("id"), source: el.getAttribute("sourceRef"), target: el.getAttribute("targetRef") }))
        .filter((f) => ids.has(f.source) && ids.has(f.target));

    return { processId, nodes, flows };
}

/** 生成不与已有元素冲突的 id (BPMN 的 id 须以字母开头) */
export function newId(prefix) {
    return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

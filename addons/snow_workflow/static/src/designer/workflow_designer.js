import { Component, onWillStart, onWillUnmount, proxy, signal, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import {
    APPROVER_TYPES,
    MAIN_PROCESS_ID,
    NODE_TYPES,
    defaultApprover,
    fromBpmnXml,
    newId,
    toBpmnXml,
    validateModel,
} from "./bpmn_model";

const CANVAS_MIN_SIZE = { width: 2000, height: 1200 };

/** 流程设计器: 从左侧拖拽节点到画布, 拖动节点移动, 从节点右侧的端点拖到另一个节点连线 */
export class WorkflowDesigner extends Component {
    static template = xml`
        <t t-name="snow_workflow.WorkflowDesigner">
            <div class="o_wf_designer">
                <div class="o_wf_designer_toolbar">
                    <span class="o_wf_designer_title"><t t-out="this.state.name"/></span>
                    <button type="button" class="btn btn-primary" t-att-disabled="this.state.saving" t-on-click="this.save">
                        <t t-out="this.texts.save"/>
                    </button>
                    <button type="button" class="btn btn-secondary" t-on-click="this.back">
                        <t t-out="this.texts.back"/>
                    </button>
                </div>
                <div class="o_wf_designer_body">
                    <div class="o_wf_palette">
                        <div class="o_wf_palette_title"><t t-out="this.texts.palette"/></div>
                        <t t-foreach="this.palette" t-as="item" t-key="item.type">
                            <div class="o_wf_palette_item" draggable="true" t-att-data-type="item.type"
                                 t-on-dragstart="(ev) => this.onPaletteDragStart(ev, item.type)">
                                <t t-out="item.label"/>
                            </div>
                        </t>
                        <div class="o_wf_palette_hint"><t t-out="this.texts.hint"/></div>
                    </div>
                    <div class="o_wf_canvas" t-ref="this.canvasRef"
                         t-att-style="this.canvasStyle"
                         t-on-dragover="this.onCanvasDragOver" t-on-drop="this.onCanvasDrop"
                         t-on-pointerdown="this.onCanvasPointerDown">
                        <svg class="o_wf_edges" t-att-width="this.canvasSize.width" t-att-height="this.canvasSize.height">
                            <defs>
                                <marker id="o_wf_arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#5a6a7a"/>
                                </marker>
                            </defs>
                            <t t-foreach="this.state.flows" t-as="flow" t-key="flow.id">
                                <path class="o_wf_flow_hit" t-att-d="this.flowPath(flow)" t-on-pointerdown="(ev) => this.selectFlow(ev, flow)"/>
                                <path t-attf-class="o_wf_flow {{ this.isSelectedFlow(flow) ? 'is_selected' : '' }}"
                                      t-att-d="this.flowPath(flow)" marker-end="url(#o_wf_arrow)"/>
                            </t>
                            <path t-if="this.state.tmpLine" class="o_wf_flow o_wf_flow_temp"
                                  t-att-d="this.tmpPath()"/>
                        </svg>
                        <t t-foreach="this.state.nodes" t-as="node" t-key="node.id">
                            <div t-attf-class="o_wf_node o_wf_node_{{ node.type }} {{ this.isSelectedNode(node) ? 'is_selected' : '' }}"
                                 t-att-data-node-id="node.id" t-att-style="this.nodeStyle(node)"
                                 t-on-pointerdown="(ev) => this.onNodePointerDown(ev, node)">
                                <span class="o_wf_node_label"><t t-out="this.labelOf(node)"/></span>
                                <span t-if="node.type !== 'end'" class="o_wf_port"
                                      t-on-pointerdown="(ev) => this.onPortPointerDown(ev, node)"/>
                            </div>
                        </t>
                    </div>
                    <div class="o_wf_properties">
                        <t t-if="this.selectedNode">
                            <div class="o_wf_properties_title"><t t-out="this.labelOf(this.selectedNode)"/></div>
                            <label class="o_wf_field">
                                <span><t t-out="this.texts.nodeName"/></span>
                                <input type="text" class="form-control" t-att-value="this.selectedNode.name"
                                       t-on-change="(ev) => this.setNodeName(this.selectedNode, ev.target.value)"/>
                            </label>
                            <t t-if="this.isApproval(this.selectedNode)">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.approver"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setApproverType(this.selectedNode, ev.target.value)">
                                        <option t-foreach="this.approverTypes" t-as="type" t-key="type"
                                                t-att-value="type" t-att-selected="this.selectedNode.approver.type === type">
                                            <t t-out="this.approverLabels[type]"/>
                                        </option>
                                    </select>
                                </label>
                                <t t-if="this.selectedNode.approver.type === 'users'">
                                    <div class="o_wf_users">
                                        <t t-foreach="this.state.users" t-as="user" t-key="user.id">
                                            <label class="o_wf_user">
                                                <input type="checkbox" t-att-checked="this.selectedNode.approver.users.includes(user.id)"
                                                       t-on-change="(ev) => this.toggleUser(this.selectedNode, user.id, ev.target.checked)"/>
                                                <span><t t-out="user.name"/></span>
                                            </label>
                                        </t>
                                    </div>
                                </t>
                                <t t-if="this.selectedNode.approver.type === 'script'">
                                    <label class="o_wf_field">
                                        <span><t t-out="this.texts.scriptKey"/></span>
                                        <input type="text" class="form-control" t-att-value="this.selectedNode.approver.script"
                                               t-on-change="(ev) => this.setScript(this.selectedNode, ev.target.value)"/>
                                    </label>
                                </t>
                            </t>
                            <button type="button" class="btn btn-outline-danger" t-on-click="this.deleteSelected">
                                <t t-out="this.texts.delete"/>
                            </button>
                        </t>
                        <t t-elif="this.selectedFlow">
                            <div class="o_wf_properties_title"><t t-out="this.texts.flow"/></div>
                            <button type="button" class="btn btn-outline-danger" t-on-click="this.deleteSelected">
                                <t t-out="this.texts.delete"/>
                            </button>
                        </t>
                        <t t-else="">
                            <div class="o_wf_properties_hint"><t t-out="this.texts.noSelection"/></div>
                        </t>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({ ...standardActionServiceProps });
    orm = useService("orm");
    actionService = useService("action");
    notification = useService("notification");
    canvasRef = signal.ref();

    texts = {
        save: _t("Save"),
        back: _t("Back"),
        palette: _t("Nodes"),
        hint: _t("Drag a node onto the canvas. Drag from the dot on the right of a node to another node to connect them."),
        nodeName: _t("Name"),
        approver: _t("Approver"),
        scriptKey: _t("Script key"),
        delete: _t("Delete"),
        flow: _t("Sequence flow"),
        noSelection: _t("Select a node or a flow to edit it."),
    };
    approverTypes = APPROVER_TYPES;
    approverLabels = {
        submitter: _t("Submitter"),
        users: _t("Specific users"),
        script: _t("Script"),
    };
    palette = Object.entries(NODE_TYPES).map(([type, info]) => ({ type, label: info.label }));
    canvasSize = { ...CANVAS_MIN_SIZE };

    state = proxy({
        name: "",
        processId: "",
        nodes: [],
        flows: [],
        selected: null,
        users: [],
        saving: false,
        tmpLine: null,
    });

    setup() {
        this.connectFrom = null;
        this.dragging = null;
        onWillStart(() => this.load());
        const onKeyDown = (ev) => this.onKeyDown(ev);
        window.addEventListener("keydown", onKeyDown);
        onWillUnmount(() => {
            window.removeEventListener("keydown", onKeyDown);
            this.stopPointerTracking();
        });
    }

    get definitionId() {
        return this.props.action.params?.definition_id;
    }

    async load() {
        const [definition] = await this.orm.read("snow.workflow.definition", [this.definitionId], [
            "name", "process_id", "content",
        ]);
        this.state.name = definition.name;
        let model;
        if (definition.content) {
            model = fromBpmnXml(definition.content);
        } else {
            model = {
                processId: MAIN_PROCESS_ID,
                nodes: [{ id: newId("n"), type: "start", name: "", x: 60, y: 120, approver: defaultApprover() }],
                flows: [],
            };
        }
        this.state.processId = model.processId;
        this.state.nodes = model.nodes;
        this.state.flows = model.flows;
        this.state.users = await this.orm.searchRead("res.users", [["active", "=", true]], ["name"], {
            limit: 500,
            order: "name",
        });
    }

    // ----- 渲染辅助 -----

    get selectedNode() {
        const selected = this.state.selected;
        return selected?.kind === "node" ? this.state.nodes.find((n) => n.id === selected.id) : null;
    }

    get selectedFlow() {
        const selected = this.state.selected;
        return selected?.kind === "flow" ? this.state.flows.find((f) => f.id === selected.id) : null;
    }

    isSelectedNode(node) {
        return this.state.selected?.kind === "node" && this.state.selected.id === node.id;
    }

    isSelectedFlow(flow) {
        return this.state.selected?.kind === "flow" && this.state.selected.id === flow.id;
    }

    isApproval(node) {
        return NODE_TYPES[node.type].approval;
    }

    labelOf(node) {
        return node.name || NODE_TYPES[node.type].label;
    }

    nodeStyle(node) {
        const [w, h] = NODE_TYPES[node.type].size;
        return `left:${node.x}px;top:${node.y}px;width:${w}px;height:${h}px;`;
    }

    get canvasStyle() {
        return `width:${this.canvasSize.width}px;height:${this.canvasSize.height}px;`;
    }

    /** 节点中心左右两侧的锚点 */
    anchorRight(node) {
        const [w, h] = NODE_TYPES[node.type].size;
        return [node.x + w, node.y + h / 2];
    }

    anchorLeft(node) {
        const [, h] = NODE_TYPES[node.type].size;
        return [node.x, node.y + h / 2];
    }

    flowPath(flow) {
        const source = this.state.nodes.find((n) => n.id === flow.source);
        const target = this.state.nodes.find((n) => n.id === flow.target);
        if (!source || !target) {
            return "";
        }
        const [x1, y1] = this.anchorRight(source);
        const [x2, y2] = this.anchorLeft(target);
        return `M ${x1} ${y1} L ${x2} ${y2}`;
    }

    tmpPath() {
        const line = this.state.tmpLine;
        return line ? `M ${line.x1} ${line.y1} L ${line.x2} ${line.y2}` : "";
    }

    // ----- 拖拽与连线 -----

    canvasPoint(ev) {
        const rect = this.canvasRef().getBoundingClientRect();
        return [ev.clientX - rect.left, ev.clientY - rect.top];
    }

    onPaletteDragStart(ev, type) {
        ev.dataTransfer.setData("text/plain", type);
        ev.dataTransfer.effectAllowed = "copy";
    }

    onCanvasDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
    }

    onCanvasDrop(ev) {
        ev.preventDefault();
        const type = ev.dataTransfer.getData("text/plain");
        if (!NODE_TYPES[type]) {
            return;
        }
        const [x, y] = this.canvasPoint(ev);
        const [w, h] = NODE_TYPES[type].size;
        this.addNode(type, x - w / 2, y - h / 2);
    }

    addNode(type, x, y) {
        const node = {
            id: newId("n"),
            type,
            name: "",
            x: Math.max(0, Math.round(x)),
            y: Math.max(0, Math.round(y)),
            approver: defaultApprover(),
        };
        this.state.nodes.push(node);
        this.state.selected = { kind: "node", id: node.id };
    }

    onCanvasPointerDown() {
        this.state.selected = null;
    }

    onNodePointerDown(ev, node) {
        if (ev.target.classList.contains("o_wf_port")) {
            return;
        }
        ev.stopPropagation();
        this.state.selected = { kind: "node", id: node.id };
        this.dragging = { node, dx: ev.clientX - node.x, dy: ev.clientY - node.y };
        this.startPointerTracking(this.onDragMove, this.onDragEnd);
    }

    onDragMove = (ev) => {
        if (!this.dragging) {
            return;
        }
        const { node, dx, dy } = this.dragging;
        node.x = Math.max(0, Math.round(ev.clientX - dx));
        node.y = Math.max(0, Math.round(ev.clientY - dy));
    };

    onDragEnd = () => {
        this.dragging = null;
        this.stopPointerTracking();
    };

    onPortPointerDown(ev, node) {
        ev.stopPropagation();
        ev.preventDefault();
        this.connectFrom = node.id;
        const [x1, y1] = this.anchorRight(node);
        this.state.tmpLine = { x1, y1, x2: x1, y2: y1 };
        this.startPointerTracking(this.onConnectMove, this.onConnectEnd);
    }

    onConnectMove = (ev) => {
        const line = this.state.tmpLine;
        if (!line) {
            return;
        }
        const [x, y] = this.canvasPoint(ev);
        line.x2 = x;
        line.y2 = y;
    };

    onConnectEnd = (ev) => {
        const from = this.connectFrom;
        this.connectFrom = null;
        this.state.tmpLine = null;
        this.stopPointerTracking();
        const target = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".o_wf_node");
        if (!target || !from) {
            return;
        }
        this.connect(from, target.dataset.nodeId);
    };

    connect(sourceId, targetId) {
        const source = this.state.nodes.find((n) => n.id === sourceId);
        const target = this.state.nodes.find((n) => n.id === targetId);
        if (!source || !target || source.id === target.id) {
            return;
        }
        if (source.type === "end" || target.type === "start") {
            this.notification.add(_t("A flow cannot start at an end event or end at the start event."), { type: "warning" });
            return;
        }
        if (this.state.flows.some((f) => f.source === sourceId && f.target === targetId)) {
            return;
        }
        const flow = { id: newId("f"), source: sourceId, target: targetId };
        this.state.flows.push(flow);
        this.state.selected = { kind: "flow", id: flow.id };
    }

    selectFlow(ev, flow) {
        ev.stopPropagation();
        this.state.selected = { kind: "flow", id: flow.id };
    }

    startPointerTracking(onMove, onUp) {
        this.stopPointerTracking();
        this.trackedMove = onMove;
        this.trackedUp = onUp;
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    stopPointerTracking() {
        if (this.trackedMove) {
            window.removeEventListener("pointermove", this.trackedMove);
            window.removeEventListener("pointerup", this.trackedUp);
            this.trackedMove = null;
            this.trackedUp = null;
        }
    }

    // ----- 属性与删除 -----

    setNodeName(node, value) {
        node.name = value.trim();
    }

    setApproverType(node, type) {
        node.approver = { ...node.approver, type };
    }

    toggleUser(node, userId, checked) {
        const users = node.approver.users.filter((id) => id !== userId);
        if (checked) {
            users.push(userId);
        }
        node.approver.users = users;
    }

    setScript(node, value) {
        node.approver.script = value.trim();
    }

    onKeyDown(ev) {
        if (ev.key !== "Delete" || ["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) {
            return;
        }
        this.deleteSelected();
    }

    deleteSelected() {
        const selected = this.state.selected;
        if (!selected) {
            return;
        }
        if (selected.kind === "node") {
            this.state.nodes = this.state.nodes.filter((n) => n.id !== selected.id);
            this.state.flows = this.state.flows.filter((f) => f.source !== selected.id && f.target !== selected.id);
        } else {
            this.state.flows = this.state.flows.filter((f) => f.id !== selected.id);
        }
        this.state.selected = null;
    }

    // ----- 保存与返回 -----

    get model() {
        return { processId: this.state.processId, nodes: this.state.nodes, flows: this.state.flows };
    }

    async save() {
        const errors = validateModel(this.model);
        if (errors.length) {
            this.notification.add(errors.join("\n"), { type: "danger", sticky: true });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("snow.workflow.definition", "save_bpmn", [this.definitionId, toBpmnXml(this.model)]);
            this.notification.add(_t("The process has been saved."), { type: "success" });
            this.back();
        } finally {
            this.state.saving = false;
        }
    }

    back() {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "snow.workflow.definition",
                res_id: this.definitionId,
                views: [[false, "form"]],
                target: "current",
            },
            { stackPosition: "replaceCurrentAction" }
        );
    }
}

registry.category("actions").add("snow_workflow_designer", WorkflowDesigner);

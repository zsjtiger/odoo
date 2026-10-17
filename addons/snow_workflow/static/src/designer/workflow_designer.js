import { Component, onWillStart, onWillUnmount, proxy, signal, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import {
    APPROVER_TYPES,
    BOUNDARY_HOSTS,
    CONDITIONAL_GATEWAYS,
    LOOP_TYPES,
    MAIN_PROCESS_ID,
    NODE_TYPES,
    SERVICE_OPERATIONS,
    TIMER_KINDS,
    decisionIdsOfDmn,
    defaultApprover,
    fromBpmnXml,
    initialProps,
    layoutScope,
    newId,
    toBpmnXml,
    validateModel,
} from "./bpmn_model";

const CANVAS_MIN_SIZE = { width: 2000, height: 1200 };

/** 流程设计器: 从左侧拖拽节点到画布, 拖动节点移动, 从节点右侧的端点拖到另一个节点连线.
 *  双击子流程进入其内部画布. 排他网关的分支可以设置条件与默认分支. */
export class WorkflowDesigner extends Component {
    static template = xml`
        <t t-name="snow_workflow.WorkflowDesigner">
            <div class="o_wf_designer">
                <div class="o_wf_designer_toolbar">
                    <span class="o_wf_designer_title"><t t-out="this.state.name"/></span>
                    <span class="o_wf_breadcrumb" t-if="this.state.path.length">
                        <t t-out="this.texts.main"/>
                        <t t-foreach="this.breadcrumb" t-as="crumb" t-key="crumb.id"> / <t t-out="crumb.label"/></t>
                    </span>
                    <button t-if="this.state.path.length" type="button" class="btn btn-secondary" t-on-click="this.leaveSubprocess">
                        <t t-out="this.texts.up"/>
                    </button>
                    <button type="button" class="btn btn-secondary" t-on-click="this.validate">
                        <t t-out="this.texts.validate"/>
                    </button>
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
                            <div t-attf-class="o_wf_palette_item o_wf_node_{{ item.type }}" draggable="true" t-att-data-type="item.type"
                                 t-on-dragstart="(ev) => this.onPaletteDragStart(ev, item.type)">
                                <t t-out="item.label"/>
                            </div>
                        </t>
                        <div class="o_wf_palette_hint"><t t-out="this.texts.hint"/></div>
                    </div>
                    <div class="o_wf_canvas" t-ref="this.canvasRef"
                         t-att-style="this.canvasStyle"
                         t-on-dragover="this.onCanvasDragOver" t-on-drop="this.onCanvasDrop"
                         t-on-pointerdown="this.onCanvasPointerDown"
                         t-on-contextmenu="this.onCanvasContextMenu">
                        <svg class="o_wf_edges" t-att-width="this.canvasSize.width" t-att-height="this.canvasSize.height">
                            <defs>
                                <marker id="o_wf_arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#5a6a7a"/>
                                </marker>
                            </defs>
                            <t t-foreach="this.scope.flows" t-as="flow" t-key="flow.id">
                                <path class="o_wf_flow_hit" t-att-d="this.flowPath(flow)" t-on-pointerdown="(ev) => this.selectFlow(ev, flow)"/>
                                <path t-attf-class="o_wf_flow {{ this.isSelectedFlow(flow) ? 'is_selected' : '' }} {{ this.isDefault(flow) ? 'is_default' : '' }}"
                                      t-att-d="this.flowPath(flow)" marker-end="url(#o_wf_arrow)"/>
                            </t>
                            <path t-if="this.state.tmpLine" class="o_wf_flow o_wf_flow_temp" t-att-d="this.tmpPath()"/>
                        </svg>
                        <t t-foreach="this.scope.nodes" t-as="node" t-key="node.id">
                            <div t-attf-class="o_wf_node o_wf_node_{{ node.type }} {{ this.isSelectedNode(node) ? 'is_selected' : '' }}"
                                 t-att-data-node-id="node.id" t-att-style="this.nodeStyle(node)"
                                 t-on-pointerdown="(ev) => this.onNodePointerDown(ev, node)"
                                 t-on-dblclick="(ev) => this.onNodeDoubleClick(ev, node)">
                                <span class="o_wf_node_label"><t t-out="this.labelOf(node)"/></span>
                                <span t-if="node.type !== 'end'" class="o_wf_port"
                                      t-on-pointerdown="(ev) => this.onPortPointerDown(ev, node)"/>
                            </div>
                        </t>
                        <div t-if="this.state.menu" class="o_wf_context_menu"
                             t-att-style="'left:' + this.state.menu.x + 'px;top:' + this.state.menu.y + 'px;'"
                             t-on-pointerdown="(ev) => ev.stopPropagation()">
                            <button type="button" class="o_wf_context_item" t-on-click="this.formatDiagram">
                                <t t-out="this.texts.format"/>
                            </button>
                            <button type="button" class="o_wf_context_item" t-on-click="this.validate">
                                <t t-out="this.texts.validate"/>
                            </button>
                        </div>
                        <t t-foreach="this.flowLabels" t-as="label" t-key="label.id">
                            <div class="o_wf_flow_label" t-att-style="label.style"><t t-out="label.text"/></div>
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
                            <t t-if="this.selectedNode.type === 'service'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.operation"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setOperation(this.selectedNode, ev.target.value)">
                                        <option t-foreach="this.operationNames" t-as="op" t-key="op"
                                                t-att-value="op" t-att-selected="this.selectedNode.operator.name === op">
                                            <t t-out="this.operationLabels[op]"/>
                                        </option>
                                    </select>
                                </label>
                                <div class="o_wf_params">
                                    <t t-foreach="this.selectedNode.operator.parameters" t-as="param" t-key="param_index">
                                        <div class="o_wf_param">
                                            <input type="text" class="form-control" t-att-value="param.name" placeholder="name"
                                                   t-on-change="(ev) => this.setParamName(this.selectedNode, param_index, ev.target.value)"/>
                                            <input type="text" class="form-control" t-att-value="param.expression" placeholder="expression"
                                                   t-on-change="(ev) => this.setParamExpression(this.selectedNode, param_index, ev.target.value)"/>
                                            <button type="button" class="btn btn-sm btn-outline-danger" t-on-click="() => this.removeParam(this.selectedNode, param_index)">×</button>
                                        </div>
                                    </t>
                                    <button type="button" class="btn btn-sm btn-secondary" t-on-click="() => this.addParam(this.selectedNode)">
                                        <t t-out="this.texts.addParam"/>
                                    </button>
                                </div>
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.resultVariable"/></span>
                                    <input type="text" class="form-control" t-att-value="this.selectedNode.operator.resultVariable"
                                           t-on-change="(ev) => this.setResultVariable(this.selectedNode, ev.target.value)"/>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'script'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.script"/></span>
                                    <textarea class="form-control o_wf_code" rows="6" t-att-value="this.selectedNode.script"
                                              t-on-change="(ev) => this.setScriptText(this.selectedNode, ev.target.value)"/>
                                </label>
                            </t>
                            <t t-if="this.isLoopable(this.selectedNode)">
                                <label class="o_wf_check">
                                    <input type="checkbox" t-att-checked="this.selectedNode.loop.enabled"
                                           t-on-change="(ev) => this.setLoop(this.selectedNode, 'enabled', ev.target.checked)"/>
                                    <span><t t-out="this.texts.multiInstance"/></span>
                                </label>
                                <t t-if="this.selectedNode.loop.enabled">
                                    <label class="o_wf_check">
                                        <input type="checkbox" t-att-checked="this.selectedNode.loop.sequential"
                                               t-on-change="(ev) => this.setLoop(this.selectedNode, 'sequential', ev.target.checked)"/>
                                        <span><t t-out="this.texts.sequential"/></span>
                                    </label>
                                    <label class="o_wf_field">
                                        <span><t t-out="this.texts.cardinality"/></span>
                                        <input type="text" class="form-control" placeholder="len(items)"
                                               t-att-value="this.selectedNode.loop.cardinality"
                                               t-on-change="(ev) => this.setLoop(this.selectedNode, 'cardinality', ev.target.value.trim())"/>
                                    </label>
                                </t>
                            </t>
                            <t t-if="this.selectedNode.type === 'business_rule'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.decision"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setDecision(this.selectedNode, ev.target.value)">
                                        <option value="" t-att-selected="!this.selectedNode.decision">-</option>
                                        <option t-foreach="this.state.decisions" t-as="decision" t-key="decision"
                                                t-att-value="decision" t-att-selected="this.selectedNode.decision === decision">
                                            <t t-out="decision"/>
                                        </option>
                                    </select>
                                </label>
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.resultVariable"/></span>
                                    <input type="text" class="form-control" t-att-value="this.selectedNode.resultVariable"
                                           t-on-change="(ev) => this.setBusinessResult(this.selectedNode, ev.target.value.trim())"/>
                                </label>
                            </t>
                            <t t-if="this.isMessageTask(this.selectedNode)">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.message"/></span>
                                    <input type="text" class="form-control" list="o_wf_messages" t-att-value="this.selectedNode.message"
                                           t-on-change="(ev) => this.setMessage(this.selectedNode, ev.target.value.trim())"/>
                                    <datalist id="o_wf_messages">
                                        <option t-foreach="this.messageNames" t-as="name" t-key="name" t-att-value="name"/>
                                    </datalist>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'send_message'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.targetRecord"/></span>
                                    <input type="text" class="form-control" t-att-value="this.selectedNode.targetRecord"
                                           placeholder="record.id" t-on-change="(ev) => this.setTargetRecord(this.selectedNode, ev.target.value.trim())"/>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'call_activity'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.calledProcess"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setCalledDefinition(this.selectedNode, ev.target.value)">
                                        <option value="" t-att-selected="!this.selectedNode.calledDefinition">-</option>
                                        <option t-foreach="this.state.definitions" t-as="definition" t-key="definition.id"
                                                t-att-value="String(definition.id)"
                                                t-att-selected="this.selectedNode.calledDefinition === String(definition.id)">
                                            <t t-out="definition.name"/>
                                        </option>
                                    </select>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'boundary_timer'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.attachedTo"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setAttachedTo(this.selectedNode, ev.target.value)">
                                        <option value="" t-att-selected="!this.selectedNode.attachedTo">-</option>
                                        <option t-foreach="this.attachableNodes" t-as="host" t-key="host.id"
                                                t-att-value="host.id" t-att-selected="this.selectedNode.attachedTo === host.id">
                                            <t t-out="this.labelOf(host)"/>
                                        </option>
                                    </select>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'timer' || this.selectedNode.type === 'boundary_timer'">
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.timerKind"/></span>
                                    <select class="form-select" t-on-change="(ev) => this.setTimerKind(this.selectedNode, ev.target.value)">
                                        <option t-foreach="this.timerKinds" t-as="kind" t-key="kind"
                                                t-att-value="kind" t-att-selected="this.selectedNode.timerKind === kind">
                                            <t t-out="this.timerKindLabels[kind]"/>
                                        </option>
                                    </select>
                                </label>
                                <label class="o_wf_field">
                                    <span><t t-out="this.texts.time"/></span>
                                    <input type="text" class="form-control" t-att-placeholder="this.timerExample"
                                           t-att-value="this.selectedNode.duration"
                                           t-on-change="(ev) => this.setDuration(this.selectedNode, ev.target.value.trim())"/>
                                </label>
                            </t>
                            <t t-if="this.selectedNode.type === 'subprocess'">
                                <button type="button" class="btn btn-secondary" t-on-click="() => this.enterSubprocess(this.selectedNode)">
                                    <t t-out="this.texts.open"/>
                                </button>
                            </t>
                            <button type="button" class="btn btn-outline-danger" t-on-click="this.deleteSelected">
                                <t t-out="this.texts.delete"/>
                            </button>
                        </t>
                        <t t-elif="this.selectedFlow">
                            <div class="o_wf_properties_title"><t t-out="this.texts.flow"/></div>
                            <t t-if="this.gatewayOfSelectedFlow">
                                <label class="o_wf_check">
                                    <input type="checkbox" t-att-checked="this.isDefault(this.selectedFlow)"
                                           t-on-change="(ev) => this.setDefault(this.selectedFlow, ev.target.checked)"/>
                                    <span><t t-out="this.texts.defaultFlow"/></span>
                                </label>
                                <label t-if="!this.isDefault(this.selectedFlow)" class="o_wf_field">
                                    <span><t t-out="this.texts.condition"/></span>
                                    <input type="text" class="form-control" t-att-value="this.selectedFlow.condition"
                                           placeholder="amount &gt; 100"
                                           t-on-change="(ev) => this.setCondition(this.selectedFlow, ev.target.value)"/>
                                </label>
                            </t>
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
        main: _t("Process"),
        up: _t("Up"),
        save: _t("Save"),
        back: _t("Back"),
        palette: _t("Nodes"),
        hint: _t("Drag a node onto the canvas. Drag from the dot on the right of a node to another node to connect them. Double-click a subprocess to edit it."),
        nodeName: _t("Name"),
        approver: _t("Approver"),
        scriptKey: _t("Script key"),
        operation: _t("Operation"),
        addParam: _t("Add a parameter"),
        resultVariable: _t("Result variable"),
        open: _t("Open subprocess"),
        delete: _t("Delete"),
        flow: _t("Sequence flow"),
        defaultFlow: _t("Default flow"),
        condition: _t("Condition"),
        noSelection: _t("Select a node or a flow to edit it."),
        script: _t("Script (Python)"),
        multiInstance: _t("Run once for each item (multi-instance)"),
        sequential: _t("One after another"),
        cardinality: _t("Number of runs"),
        decision: _t("Decision"),
        message: _t("Message name"),
        targetRecord: _t("Target record (Python expression, empty = inside this process)"),
        timerKind: _t("Timer type"),
        attachedTo: _t("Attached to"),
        calledProcess: _t("Process to call"),
        time: _t("Time (quoted expression is added automatically)"),
        format: _t("Format diagram"),
        validate: _t("Validate"),
        valid: _t("The process is valid."),
        formatted: _t("The diagram has been formatted."),
    };
    timerKinds = Object.keys(TIMER_KINDS);
    timerKindLabels = Object.fromEntries(Object.entries(TIMER_KINDS).map(([kind, info]) => [kind, info.label]));

    get timerExample() {
        const kind = this.selectedNode?.timerKind || "duration";
        return TIMER_KINDS[kind].example;
    }

    /** 边界定时器可以挂接的自动节点 (当前作用域中) */
    get attachableNodes() {
        return this.scope.nodes.filter((n) => BOUNDARY_HOSTS.includes(n.type));
    }

    setCalledDefinition(node, id) {
        node.calledDefinition = id;
    }

    setAttachedTo(node, id) {
        node.attachedTo = id;
    }

    setTimerKind(node, kind) {
        node.timerKind = kind;
        node.duration = TIMER_KINDS[kind].example;
    }
    approverTypes = APPROVER_TYPES;
    approverLabels = {
        submitter: _t("Submitter"),
        users: _t("Specific users"),
        script: _t("Script"),
    };
    operationNames = Object.keys(SERVICE_OPERATIONS);
    operationLabels = Object.fromEntries(
        Object.entries(SERVICE_OPERATIONS).map(([name, info]) => [name, info.label])
    );
    palette = Object.entries(NODE_TYPES).map(([type, info]) => ({ type, label: info.label }));
    canvasSize = { ...CANVAS_MIN_SIZE };

    state = proxy({
        name: "",
        model: { processId: MAIN_PROCESS_ID, nodes: [], flows: [] },
        path: [],
        selected: null,
        users: [],
        decisions: [],
        definitions: [],
        saving: false,
        tmpLine: null,
        menu: null,
    });

    setup() {
        this.connectFrom = null;
        this.dragging = null;
        this.unsupported = [];
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
            "name", "content", "dmn_content",
        ]);
        this.state.name = definition.name;
        this.state.decisions = decisionIdsOfDmn(definition.dmn_content);
        if (definition.content) {
            const model = fromBpmnXml(definition.content);
            this.unsupported = model.unsupported;
            this.state.model = { processId: model.processId, nodes: model.nodes, flows: model.flows };
        } else {
            this.state.model.nodes = [{ id: newId("n"), type: "start", name: "", x: 60, y: 120, approver: defaultApprover() }];
        }
        if (this.unsupported.length) {
            this.notification.add(
                this.unsupported.map((name) => _t("The element “%s” is not supported by the designer yet.", name)).join("\n"),
                { type: "warning", sticky: true }
            );
        }
        // 调用活动可以调用其它流程定义 (不包括本流程)
        this.state.definitions = await this.orm.searchRead("snow.workflow.definition",
            [["id", "!=", this.definitionId], ["active", "=", true]], ["name"], { order: "name" });
        this.state.users = await this.orm.searchRead("res.users", [["active", "=", true]], ["name"], {
            limit: 500,
            order: "name",
        });
    }

    // ----- 作用域 (流程 / 子流程) -----

    /** 当前正在编辑的作用域 {nodes, flows} */
    get scope() {
        let scope = this.state.model;
        for (const id of this.state.path) {
            scope = scope.nodes.find((n) => n.id === id).children;
        }
        return scope;
    }

    get breadcrumb() {
        const crumbs = [];
        let scope = this.state.model;
        for (const id of this.state.path) {
            const node = scope.nodes.find((n) => n.id === id);
            crumbs.push({ id, label: node.name || NODE_TYPES.subprocess.label });
            scope = node.children;
        }
        return crumbs;
    }

    enterSubprocess(node) {
        this.state.path.push(node.id);
        this.state.selected = null;
    }

    leaveSubprocess() {
        this.state.path.pop();
        this.state.selected = null;
    }

    onNodeDoubleClick(ev, node) {
        if (node.type === "subprocess") {
            ev.stopPropagation();
            this.enterSubprocess(node);
        }
    }

    // ----- 渲染辅助 -----

    get selectedNode() {
        const selected = this.state.selected;
        return selected?.kind === "node" ? this.scope.nodes.find((n) => n.id === selected.id) : null;
    }

    get selectedFlow() {
        const selected = this.state.selected;
        return selected?.kind === "flow" ? this.scope.flows.find((f) => f.id === selected.id) : null;
    }

    get gatewayOfSelectedFlow() {
        const flow = this.selectedFlow;
        return flow && CONDITIONAL_GATEWAYS.includes(this.scope.nodes.find((n) => n.id === flow.source)?.type);
    }

    get flowLabels() {
        return this.scope.flows
            .filter((f) => CONDITIONAL_GATEWAYS.includes(this.scope.nodes.find((n) => n.id === f.source)?.type))
            .map((f) => {
                // 条件标签靠近网关出口, 避免压在目标节点上
                const [x1, y1] = this.flowPoint(f, 0.35);
                const text = this.isDefault(f) ? _t("default") : f.condition || "?";
                return { id: f.id, text, style: `left:${x1}px;top:${y1 - 22}px;` };
            });
    }

    isSelectedNode(node) {
        return this.state.selected?.kind === "node" && this.state.selected.id === node.id;
    }

    isSelectedFlow(flow) {
        return this.state.selected?.kind === "flow" && this.state.selected.id === flow.id;
    }

    isDefault(flow) {
        const source = this.scope.nodes.find((n) => n.id === flow.source);
        return CONDITIONAL_GATEWAYS.includes(source?.type) && source.defaultFlow === flow.id;
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

    flowEnds(flow) {
        const source = this.scope.nodes.find((n) => n.id === flow.source);
        const target = this.scope.nodes.find((n) => n.id === flow.target);
        return source && target ? [this.anchorRight(source), this.anchorLeft(target)] : null;
    }

    flowMidpoint(flow) {
        const ends = this.flowEnds(flow);
        return ends ? [(ends[0][0] + ends[1][0]) / 2, (ends[0][1] + ends[1][1]) / 2] : [0, 0];
    }

    flowPoint(flow, t) {
        const ends = this.flowEnds(flow);
        return ends ? [ends[0][0] + (ends[1][0] - ends[0][0]) * t, ends[0][1] + (ends[1][1] - ends[0][1]) * t] : [0, 0];
    }

    flowPath(flow) {
        const ends = this.flowEnds(flow);
        if (!ends) {
            return "";
        }
        const [[x1, y1], [x2, y2]] = ends;
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
            ...initialProps(type),
        };
        if (type === "subprocess") {
            node.children = { nodes: [], flows: [] };
            node.children.nodes.push({ id: newId("n"), type: "start", name: "", x: 30, y: 30, approver: defaultApprover() });
            node.children.nodes.push({ id: newId("n"), type: "end", name: "", x: 300, y: 30, approver: defaultApprover() });
        }
        this.scope.nodes.push(node);
        this.state.selected = { kind: "node", id: node.id };
    }

    onCanvasPointerDown() {
        this.state.selected = null;
        this.state.menu = null;
    }

    onCanvasContextMenu(ev) {
        ev.preventDefault();
        const [x, y] = this.canvasPoint(ev);
        this.state.menu = { x, y };
    }

    /** 右键菜单: 按流程顺序整理节点的位置 */
    formatDiagram() {
        this.state.menu = null;
        const positions = layoutScope(this.scope);
        for (const node of this.scope.nodes) {
            if (positions[node.id]) {
                Object.assign(node, positions[node.id]);
            }
        }
        this.notification.add(this.texts.formatted, { type: "success" });
    }

    /** 验证按钮: 先检查画布上的结构, 再由服务器用保存时同样的检查验证, 不写入 */
    async validate() {
        this.state.menu = null;
        const errors = validateModel(this.state.model, this.unsupported, this.state.decisions);
        if (errors.length) {
            this.notification.add(errors.join("\n"), { type: "danger", sticky: true });
            return false;
        }
        const result = await this.orm.call("snow.workflow.definition", "validate_bpmn",
            [this.definitionId, toBpmnXml(this.state.model)]);
        if (!result.valid) {
            this.notification.add(result.message, { type: "danger", sticky: true });
            return false;
        }
        this.notification.add(this.texts.valid, { type: "success" });
        return true;
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
        const source = this.scope.nodes.find((n) => n.id === sourceId);
        const target = this.scope.nodes.find((n) => n.id === targetId);
        if (!source || !target || source.id === target.id) {
            return;
        }
        if (source.type === "end" || target.type === "start") {
            this.notification.add(_t("A flow cannot start at an end event or end at the start event."), { type: "warning" });
            return;
        }
        if (this.scope.flows.some((f) => f.source === sourceId && f.target === targetId)) {
            return;
        }
        const flow = { id: newId("f"), source: sourceId, target: targetId, condition: "" };
        this.scope.flows.push(flow);
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

    // ----- 属性 -----

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

    setScriptText(node, value) {
        node.script = value;
    }

    isLoopable(node) {
        return LOOP_TYPES.includes(node.type);
    }

    setLoop(node, field, value) {
        node.loop = { ...node.loop, [field]: value };
    }

    isMessageTask(node) {
        return node.type === "send_message" || node.type === "receive_message";
    }

    /** 模型中已经使用的消息名 (用于接收/发送任务的选择) */
    get messageNames() {
        const names = new Set();
        const visit = (scope) => {
            for (const node of scope.nodes) {
                if (this.isMessageTask(node) && node.message) {
                    names.add(node.message);
                }
                if (node.type === "subprocess") {
                    visit(node.children);
                }
            }
        };
        visit(this.state.model);
        return [...names];
    }

    setDecision(node, value) {
        node.decision = value;
    }

    setBusinessResult(node, value) {
        node.resultVariable = value;
    }

    setMessage(node, value) {
        node.message = value;
    }

    setTargetRecord(node, value) {
        node.targetRecord = value;
    }

    setDuration(node, value) {
        node.duration = value;
    }

    setOperation(node, name) {
        node.operator.name = name;
        if (name === "evaluate" && !node.operator.parameters.some((p) => p.name === "value")) {
            node.operator.parameters.unshift({ name: "value", expression: "" });
        }
    }

    setParamName(node, index, value) {
        node.operator.parameters[index].name = value.trim();
    }

    setParamExpression(node, index, value) {
        node.operator.parameters[index].expression = value.trim();
    }

    addParam(node) {
        node.operator.parameters.push({ name: "", expression: "" });
    }

    removeParam(node, index) {
        node.operator.parameters.splice(index, 1);
    }

    setResultVariable(node, value) {
        node.operator.resultVariable = value.trim();
    }

    setDefault(flow, checked) {
        const gateway = this.scope.nodes.find((n) => n.id === flow.source);
        gateway.defaultFlow = checked ? flow.id : "";
    }

    setCondition(flow, value) {
        flow.condition = value.trim();
    }

    onKeyDown(ev) {
        if (ev.key === "Escape") {
            this.state.menu = null;
            return;
        }
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
        const scope = this.scope;
        if (selected.kind === "node") {
            scope.nodes = scope.nodes.filter((n) => n.id !== selected.id);
            scope.flows = scope.flows.filter((f) => f.source !== selected.id && f.target !== selected.id);
        } else {
            scope.flows = scope.flows.filter((f) => f.id !== selected.id);
            for (const gateway of scope.nodes) {
                if (gateway.defaultFlow === selected.id) {
                    gateway.defaultFlow = "";
                }
            }
        }
        this.state.selected = null;
    }

    // ----- 保存与返回 -----

    async save() {
        const errors = validateModel(this.state.model, this.unsupported, this.state.decisions);
        if (errors.length) {
            this.notification.add(errors.join("\n"), { type: "danger", sticky: true });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("snow.workflow.definition", "save_bpmn", [this.definitionId, toBpmnXml(this.state.model)]);
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

import { Component, proxy, onWillStart, t, useProps, xml } from "@odoo/owl";
import { makeContext } from "@web/core/data/context";
import { evaluateExpr } from "@web/core/data/py_js/py";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { parseXML } from "@web/core/utils/xml";
import { rpc } from "@web/core/services/network/rpc";
import { user } from "@web/core/services/user";
import { View } from "@web/views/view";

const DEFAULT_GRID = 4;
const MIN_CELL_HEIGHT = 280;

/**
 * 解析仪表盘的 arch: <board layout="R-C"> 下的 <action> 子节点.
 *
 * @returns {{layout: string, actions: Object[]}}
 */
export function parseBoardArch(arch) {
    // arch 可能是字符串, 也可能已经是解析好的 XML 节点
    const root = typeof arch === "string" || !arch ? parseXML(arch || "<board/>") : arch;
    const board = root.tagName === "board" ? root : root.querySelector("board");
    if (!board) {
        return { layout: "", actions: [] };
    }
    const actions = [...board.children]
        .filter((node) => node.tagName === "action")
        .map((node, index) => ({
            key: `action_${index}`,
            string: node.getAttribute("string") || "",
            name: node.getAttribute("name"),
            viewMode: node.getAttribute("view_mode") || "list",
            layout: node.getAttribute("layout") || "1-1",
            fold: ["1", "True"].includes(node.getAttribute("fold")),
            domain: node.getAttribute("domain") || "[]",
            context: node.getAttribute("context") || "{}",
        }));
    return { layout: board.getAttribute("layout") || "", actions };
}

/**
 * 按 layout 把各动作放进网格 (与旧版的算法一致: 从左上角开始找第一个能放下的位置).
 *
 * @returns {{action: Object, placed: boolean, style: string}[]}
 */
export function computePlacements(layout, actions) {
    let rows = DEFAULT_GRID;
    let cols = DEFAULT_GRID;
    const [layoutRows, layoutCols] = (layout || "").split("-").map(Number);
    if (layoutRows > 0 && layoutCols > 0) {
        rows = layoutRows;
        cols = layoutCols;
    }
    const occupied = Array.from({ length: rows }, () => Array(cols).fill(false));

    const canPlace = (row, col, w, h) => {
        if (col + w > cols || row + h > rows) {
            return false;
        }
        for (let r = row; r < row + h; r++) {
            for (let c = col; c < col + w; c++) {
                if (occupied[r][c]) {
                    return false;
                }
            }
        }
        return true;
    };
    const mark = (row, col, w, h) => {
        for (let r = row; r < row + h; r++) {
            for (let c = col; c < col + w; c++) {
                occupied[r][c] = true;
            }
        }
    };

    return actions.map((action) => {
        const [h, w] = action.layout.split("-").map((n) => Math.max(1, Number(n) || 1));
        for (let row = 0; row < rows; row++) {
            for (let col = 0; col < cols; col++) {
                if (canPlace(row, col, w, h)) {
                    mark(row, col, w, h);
                    return {
                        action,
                        placed: true,
                        style: `grid-column: ${col + 1} / span ${w}; grid-row: ${row + 1} / span ${h};`,
                    };
                }
            }
        }
        return { action, placed: false, style: "" };
    });
}

/**
 * 仪表盘的一个格子: 加载动作, 并用 View 组件渲染其中的视图 (不显示搜索与操作栏).
 */
export class BoardActionCell extends Component {
    static template = xml`
        <t t-name="board.BoardActionCell">
            <h2 t-if="this.props.action.string" class="o_board_action_title" t-on-click="this.toggleFold">
                <t t-esc="this.props.action.string"/>
            </h2>
            <div t-if="!this.state.folded" class="o_board_action_content">
                <View t-if="this.state.viewProps" t-props="this.state.viewProps"/>
                <p t-elif="this.state.error" class="o_board_action_error"><t t-esc="this.state.error"/></p>
            </div>
        </t>
    `;
    static components = { View };

    props = useProps({ action: t.object() });
    state = proxy({ viewProps: null, error: "", folded: false });

    setup() {
        this.state.folded = this.props.action.fold;
        onWillStart(() => this.load());
    }

    toggleFold() {
        this.state.folded = !this.state.folded;
    }

    async load() {
        const { action: descr } = this.props;
        try {
            const actionId = /^\d+$/.test(descr.name) ? Number(descr.name) : descr.name;
            const action = await rpc("/web/action/load", {
                action_id: actionId,
                context: makeContext([user.context]),
            });
            const evalContext = { ...user.context };
            const context = { ...user.context, ...action.context, ...evaluateExpr(descr.context, evalContext) };
            const domain = evaluateExpr(descr.domain, context);
            const viewType = descr.viewMode.split(",")[0].trim();
            this.state.viewProps = {
                resModel: action.res_model,
                type: viewType,
                views: action.views,
                context,
                domain,
                display: { controlPanel: false },
                loadIrFilters: false,
                className: "o_board_action_view",
            };
        } catch (error) {
            this.state.error = _t("This action can not be displayed: %s", descr.name);
            console.error(error);
        }
    }
}

/**
 * 仪表盘控制器: 按网格摆放各个格子.
 */
export class BoardController extends Component {
    static template = xml`
        <t t-name="board.BoardController">
            <div class="o_board_view">
                <div t-if="!this.props.actions.length" class="o_view_nocontent">
                    <p class="o_board_empty"><t t-esc="this.texts.empty"/></p>
                </div>
                <div t-else="" class="o_board_grid" t-att-style="this.gridStyle">
                    <t t-foreach="this.placements" t-as="placement" t-key="placement.action.key">
                        <div t-if="placement.placed" class="o_board_action" t-att-style="placement.style">
                            <BoardActionCell action="placement.action"/>
                        </div>
                    </t>
                </div>
            </div>
        </t>
    `;
    static components = { BoardActionCell };

    props = useProps({
        layout: t.string().optional(""),
        actions: t.array().optional([]),
    });
    texts = { empty: _t("Your personal dashboard is empty") };

    get placements() {
        return computePlacements(this.props.layout, this.props.actions);
    }

    get gridStyle() {
        const [rows, cols] = (this.props.layout || "").split("-").map(Number);
        const r = rows > 0 ? rows : DEFAULT_GRID;
        const c = cols > 0 ? cols : DEFAULT_GRID;
        return `grid-template-columns: repeat(${c}, minmax(0, 1fr)); grid-template-rows: repeat(${r}, minmax(${MIN_CELL_HEIGHT}px, auto));`;
    }
}

export const boardView = {
    type: "form",
    searchMenuTypes: [],
    Controller: BoardController,

    props(genericProps) {
        const { layout, actions } = parseBoardArch(genericProps.arch);
        return { ...genericProps, layout, actions };
    },
};

registry.category("views").add("board", boardView);

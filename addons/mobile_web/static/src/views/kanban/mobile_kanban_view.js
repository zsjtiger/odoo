import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ActionSheet } from "@mobile_web/widgets/action_sheet/action_sheet";
import { ConfirmSheet, useConfirmSheet } from "@mobile_web/widgets/confirm_sheet/confirm_sheet";
import { SortMenu } from "@mobile_web/widgets/sort_menu/sort_menu";
import { sortableFields } from "@mobile_web/views/record_filters";
import { buttonItems, collectButtons, runRecordButton } from "@mobile_web/actions/record_buttons";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames, isHiddenColumn, splitColumns } from "@mobile_web/views/arch";
import { getFieldWidget } from "@mobile_web/fields/index";
import { MobileRecordModel } from "@mobile_web/views/record_model";
import { RecordCollection } from "@mobile_web/views/record_list";
import { hasDisplayValue } from "@mobile_web/fields/field_utils";
import { useInfiniteScroll } from "@mobile_web/views/infinite_scroll";
import { pullLabel, usePullToRefresh } from "@mobile_web/views/pull_to_refresh";
import { readonlyFieldRecord } from "@mobile_web/fields/field_record";
import { _t } from "@web/core/data/l10n/translation";
import { notify } from "@mobile_web/core/notification";

/**
 * 找到卡片的字段布局: 优先使用 templates 中的 card 模板, 否则使用看板根节点下的字段
 *
 * @param {import("@mobile_web/views/arch").ArchNode} root
 * @returns {import("@mobile_web/views/arch").ArchNode[]} 卡片内的节点
 */
function findCardNodes(root) {
    const templates = root.children.find((c) => c.tag === "templates");
    const card = templates && templates.children.find((c) => c.tag === "t" && c.attrs["t-name"] === "card");
    return card ? card.children : root.children;
}

/**
 * 卡片中的字段节点: 字段可能嵌套在 div / span 等容器中, 递归收集(跳过隐藏的字段)
 *
 * @param {import("@mobile_web/views/arch").ArchNode[]} nodes
 * @returns {import("@mobile_web/views/arch").ArchNode[]}
 */
function collectCardFields(nodes) {
    const fields = [];
    for (const node of nodes) {
        if (node.tag === "field" && node.attrs.name) {
            if (!isHiddenColumn(node)) {
                fields.push(node);
            }
            continue;
        }
        fields.push(...collectCardFields(node.children));
    }
    return fields;
}

/**
 * 移动端看板视图: 以卡片的形式展示记录, 标题为第一个字段, 其余字段作为卡片内容
 *
 * 只支持 arch 中的字段, 不解析 QWeb 的条件/样式指令
 */
// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    moreActions: _t("More actions"),
    actionFailed: _t("Action failed"),
    loadFailed: _t("Failed to load, please try again"),
    noRecords: _t("No records"),
    loading: _t("Loading…"),
};

export class MobileKanbanView extends Component {
    texts = TEXTS;
    static components = { ActionSheet, SortMenu, ConfirmSheet };
    static template = xml`
        <t t-name="mobile_web.MobileKanbanView">
            <div class="m_kanban_view" t-ref="this.pull.container">
                <div t-if="this.pull.state.distance > 0 or this.pull.state.refreshing" class="m_pull_indicator" t-att-style="'height: ' + this.pull.state.distance + 'px'"><t t-esc="this.pullText"/></div>
                <div t-if="this.sortFields.length" class="m_list_meta">
                    <SortMenu sortFields="this.sortFields" onChange="this.onSort"/>
                </div>
                <ul class="m_kanban">
                    <li t-foreach="this.collection.state.records" t-as="record" t-key="record.resId"
                        t-attf-class="{{ this.rowButtons.length ? 'has_more' : '' }}">
                        <button type="button" class="m_kanban_card" t-att-data-id="record.resId" t-on-click="this.onCardClick">
                            <div class="m_kanban_title" t-if="this.title">
                                <t t-component="this.getWidget(this.title)" t-props="this.cellProps(this.title, record)"/>
                            </div>
                            <div class="m_kanban_lines" t-if="this.lines.length">
                                <span class="m_kanban_line" t-foreach="this.lines" t-as="column" t-key="column.name" t-if="this.hasValue(column, record)">
                                    <t t-component="this.getWidget(column)" t-props="this.cellProps(column, record)"/>
                                </span>
                            </div>
                        </button>
                        <button t-if="this.rowButtons.length" type="button" class="m_row_more" t-att-data-id="record.resId" t-att-aria-label="this.texts.moreActions" t-on-click="this.onMoreClick">⋯</button>
                    </li>
                </ul>
                <ActionSheet t-if="this.state.sheet" items="this.sheetItems" onClose="this.closeSheet"/>
                <ConfirmSheet t-if="this.confirmSheet.state.dialog" t-props="this.confirmSheet.state.dialog" onAnswer="this.confirmSheet.answer"/>
                <p t-if="this.collection.state.error" class="m_error"><t t-esc="this.texts.loadFailed"/></p>
                <p t-if="!this.collection.state.loading and this.collection.state.total === 0" class="m_empty"><t t-esc="this.texts.noRecords"/></p>
                <div t-ref="this.infinite.sentinel" class="m_load_sentinel">
                    <t t-esc="this.sentinelText"/>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        resModel: t.string(),
        arch: t.string(),
        fields: t.object(),
        domain: t.array().optional([]),
        context: t.object().optional({}),
        onSelect: t.function(),
    });
    orm = useService("orm");
    notification = useService("notification");
    mobileAction = useService("mobileAction");
    state = proxy({ sheet: null });
    confirmSheet = useConfirmSheet();

    setup() {
        const root = parseArch(this.props.arch);
        this.rowButtons = collectButtons(root);
        const cardNodes = collectCardFields(findCardNodes(root));
        const columns = cardNodes.map((n) => ({ name: n.attrs.name, attrs: n.attrs, field: this.props.fields[n.attrs.name] }));
        const { primary, secondary } = splitColumns(columns);
        this.title = primary;
        this.lines = secondary;
        const sortInfo = columns;
        this.sortFields = sortableFields(sortInfo);
        const fieldNames = [...collectFieldNames(root)];
        this.collection = new RecordCollection(
            new MobileRecordModel(this.orm, this.props.resModel, this.props.fields, this.props.context),
            fieldNames
        );
        onWillStart(() => this.reloadCollection());
        this.infinite = useInfiniteScroll(this.collection);
        this.pull = usePullToRefresh(() => this.reloadCollection());
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(this.combinedDomain(nextProps)) !== JSON.stringify(this.collection.domain)) {
                return this.reloadCollection(nextProps).then(() => this.infinite.recheck());
            }
        });
    }

    hasValue(column, record) {
        return hasDisplayValue(record.data[column.name]);
    }

    getWidget(column) {
        return getFieldWidget(column.attrs, column.field);
    }

    cellProps(column, record) {
        return {
            name: column.name,
            field: column.field,
            record: readonlyFieldRecord(record),
            readonly: true,
            compact: true,
            attrs: column.attrs,
            onChange: () => {},
            resModel: this.props.resModel,
        };
    }

    get sentinelText() {
        return this.collection.state.loading ? this.texts.loading : "";
    }

    /** 记录上的操作弹层 */
    get sheetItems() {
        const sheet = this.state.sheet;
        if (!sheet) {
            return [];
        }
        return buttonItems(this.rowButtons, sheet.record.data, (node) => () => this.runRowButton(node, sheet.record));
    }

    onMoreClick(ev) {
        const id = Number(ev.currentTarget.dataset.id);
        const record = this.collection.state.records.find((r) => r.resId === id);
        if (record) {
            this.state.sheet = { record };
        }
    }

    closeSheet = () => {
        this.state.sheet = null;
    };

    /** 执行一条记录的操作; 对象方法可能改变数据, 此时重新加载列表 */
    runRowButton = async (node, record) => {
        try {
            const reload = await runRecordButton({
                node,
                resModel: this.props.resModel,
                resIds: [record.resId],
                context: this.props.context,
                orm: this.orm,
                mobileAction: this.mobileAction,
                confirm: this.confirmSheet.ask,
            });
            if (reload) {
                await this.reloadCollection();
            }
        } catch (error) {
            notify(this.notification, error?.data?.message || error?.message || this.texts.actionFailed, {
                type: "danger",
                sticky: true,
            });
        }
    };

    /** 视图的 domain 与排序/筛选条件合并后查询 */
    combinedDomain(props = this.props) {
        return props.domain || [];
    }

    reloadCollection(props = this.props) {
        return this.collection.reload(this.combinedDomain(props), this.collection.order);
    }

    /** 排序菜单的变化: 按新的排序重新加载第一页 */
    // 作为子组件的回调传递, 使用箭头函数保持 this
    onSort = ({ order }) => {
        return this.collection.reload(this.combinedDomain(), order);
    };

    onCardClick(ev) {
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    /** 下拉刷新时的提示文字 */
    get pullText() {
        return pullLabel(this.pull.state);
    }
}

mobileViewRegistry.add("kanban", MobileKanbanView);

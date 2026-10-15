import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames, isHiddenColumn, splitColumns } from "@mobile_web/views/arch";
import { getFieldWidget } from "@mobile_web/fields/index";
import { MobileRecordModel } from "@mobile_web/views/record_model";
import { RecordCollection } from "@mobile_web/views/record_list";
import { hasDisplayValue } from "@mobile_web/fields/field_utils";
import { useInfiniteScroll } from "@mobile_web/views/infinite_scroll";
import { pullLabel, usePullToRefresh } from "@mobile_web/views/pull_to_refresh";
import { ActionSheet } from "@mobile_web/widgets/action_sheet/action_sheet";
import { SortMenu } from "@mobile_web/widgets/sort_menu/sort_menu";
import { sortableFields } from "@mobile_web/views/record_filters";
import { buttonItems, collectButtons, runRecordButton } from "@mobile_web/actions/record_buttons";
import { readonlyFieldRecord } from "@mobile_web/fields/field_record";
import { _t } from "@web/core/data/l10n/translation";
import { notify } from "@mobile_web/core/notification";
import { SwipeRow } from "@mobile_web/widgets/swipe_row/swipe_row";
import { ConfirmSheet, useConfirmSheet } from "@mobile_web/widgets/confirm_sheet/confirm_sheet";
import { canDeleteRecords, deleteRecords } from "@mobile_web/views/record_delete";

/**
 * 移动端列表视图: 每行一张卡片式的行, 第一列作为标题, 后面的列作为副标题
 *
 * 点击整行进入表单; 底部"加载更多"分页, 避免一次加载过多数据
 */
// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
/** 两次点击同一行的最大间隔 (毫秒), 超过则视为两次单击 */
const DOUBLE_TAP_DELAY = 350;

/** 字段节点的 class 中是否包含 name */
function hasClass(column, name) {
    return (column.attrs.class || "").split(/\s+/).includes(name);
}

/**
 * 判断 decoration-* 的条件 "字段 == '值'" 是否成立 (值与字段的显示值以字符串比较)
 */
function decorationMatches(expr, record) {
    const match = /^\s*(\w+)\s*==\s*['"]?([^'"]*)['"]?\s*$/.exec(expr || "");
    if (!match) {
        return false;
    }
    return String(record.data[match[1]]) === match[2];
}

const TEXTS = {
    moreActions: _t("More actions"),
    delete: _t("Delete"),
    confirmDelete: _t("Delete this record?"),
    actionFailed: _t("Action failed"),
    loadFailed: _t("Failed to load, please try again"),
    noRecords: _t("No records"),
    loading: _t("Loading…"),
};

export class MobileListView extends Component {
    texts = TEXTS;
    static components = { ActionSheet, SortMenu, SwipeRow, ConfirmSheet };
    static template = xml`
        <t t-name="mobile_web.MobileListView">
            <div class="m_list_view" t-ref="this.pull.container">
                <div t-if="this.pull.state.distance > 0 or this.pull.state.refreshing" class="m_pull_indicator" t-att-style="'height: ' + this.pull.state.distance + 'px'"><t t-esc="this.pullText"/></div>
                <div t-if="this.sortFields.length" class="m_list_meta">
                    <SortMenu sortFields="this.sortFields" onChange="this.onSort"/>
                </div>
                <ul class="m_list">
                    <li t-foreach="this.collection.state.records" t-as="record" t-key="record.resId"
                        t-attf-class="{{ this.rowButtons.length ? 'has_more' : '' }}">
                        <SwipeRow resId="record.resId" disabled="!this.canDelete" label="this.texts.delete" onDelete="this.onDeleteRow">
                            <button type="button" class="m_list_row m_list_card" t-att-data-id="record.resId" t-on-click="this.onRowClick">
                                <div t-if="this.image and this.hasValue(this.image, record)" class="m_card_image">
                                    <t t-component="this.getWidget(this.image)" t-props="this.cellProps(this.image, record)"/>
                                </div>
                                <div class="m_card_head">
                                    <div class="m_list_primary">
                                        <t t-if="this.primary" t-component="this.getWidget(this.primary)" t-props="this.cellProps(this.primary, record)"/>
                                    </div>
                                    <span t-if="this.badge and this.hasValue(this.badge, record)" t-attf-class="m_card_badge {{ this.toneOf(this.badge, record) }}">
                                        <t t-component="this.getWidget(this.badge)" t-props="this.cellProps(this.badge, record)"/>
                                    </span>
                                </div>
                                <div t-if="this.subtitle and this.hasValue(this.subtitle, record)" class="m_card_sub">
                                    <t t-component="this.getWidget(this.subtitle)" t-props="this.cellProps(this.subtitle, record)"/>
                                </div>
                                <div t-if="this.secondary.length or this.dateColumn" class="m_card_foot">
                                    <span class="m_card_lines">
                                        <t t-foreach="this.secondary" t-as="column" t-key="column.name">
                                            <span class="m_card_line" t-if="this.hasValue(column, record)">
                                                <t t-component="this.getWidget(column)" t-props="this.cellProps(column, record)"/>
                                            </span>
                                        </t>
                                    </span>
                                    <span t-if="this.dateColumn and this.hasValue(this.dateColumn, record)" class="m_card_date">
                                        <t t-component="this.getWidget(this.dateColumn)" t-props="this.cellProps(this.dateColumn, record)"/>
                                    </span>
                                </div>
                            </button>
                            <button t-if="this.rowButtons.length" type="button" class="m_row_more" t-att-data-id="record.resId" t-att-aria-label="this.texts.moreActions" t-on-click="this.onMoreClick">⋯</button>
                        </SwipeRow>
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
    lastRowClick = { id: null, time: 0 };
    confirmSheet = useConfirmSheet();

    setup() {
        const node = parseArch(this.props.arch);
        this.rowButtons = collectButtons(node);
        const columns = node.children.filter((c) => c.tag === "field" && c.attrs.name && !isHiddenColumn(c));
        const cols = columns.map((c) => this.column(c));
        // 图片字段单独展示在卡片最前面, 不参与标题与底部字段的选择
        this.image = cols.find((c) => c.attrs.widget === "image") || null;
        const textCols = cols.filter((c) => c !== this.image);
        const { primary, secondary } = splitColumns(textCols);
        this.primary = primary;
        // 卡片布局: 用 class 标记的字段显示在固定的位置, 其余字段排在底部
        this.badge = cols.find((c) => hasClass(c, "mobile_badge")) || null;
        this.subtitle = cols.find((c) => hasClass(c, "mobile_subtitle")) || null;
        this.dateColumn = cols.find((c) => hasClass(c, "mobile_date")) || null;
        const placed = [this.badge, this.subtitle, this.dateColumn];
        this.secondary = secondary.filter((c) => !placed.includes(c));
        const sortInfo = columns.map((c) => this.column(c));
        this.sortFields = sortableFields(sortInfo);
        const fieldNames = [...collectFieldNames(node)];
        this.collection = new RecordCollection(this.makeModel(), fieldNames);
        // 删除权限在首次渲染前确定, 没有权限时删除按钮不可用
        this.allowDelete = node.attrs.delete !== "0";
        this.canDelete = false;
        onWillStart(async () => {
            this.canDelete = this.allowDelete && (await canDeleteRecords(this.orm, this.props.resModel));
            await this.reloadCollection();
        });
        this.infinite = useInfiniteScroll(this.collection);
        this.pull = usePullToRefresh(() => this.reloadCollection());
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(this.combinedDomain(nextProps)) !== JSON.stringify(this.collection.domain)) {
                return this.reloadCollection(nextProps).then(() => this.infinite.recheck());
            }
        });
    }

    makeModel() {
        return new MobileRecordModel(this.orm, this.props.resModel, this.props.fields, this.props.context);
    }

    column(node) {
        return { name: node.attrs.name, attrs: node.attrs, field: this.props.fields[node.attrs.name] };
    }

    hasValue(column, record) {
        return hasDisplayValue(record.data[column.name]);
    }

    /**
     * 状态胶囊的颜色: decoration-success / decoration-danger 为 "字段 == '值'" 形式的条件
     *
     * @param {{ attrs: Object<string, string> }} column
     * @param {{ data: Object }} record
     */
    toneOf(column, record) {
        if (decorationMatches(column.attrs["decoration-success"], record)) {
            return "is_success";
        }
        if (decorationMatches(column.attrs["decoration-danger"], record)) {
            return "is_danger";
        }
        return "";
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

    /** 左滑删除: 确认后调用服务端删除, 再重新加载第一页 */
    // 作为子组件的回调传递, 使用箭头函数保持 this
    onDeleteRow = async (resId) => {
        if (!this.canDelete) {
            return;
        }
        const confirmed = await this.confirmSheet.ask(this.texts.confirmDelete, {
            confirmLabel: this.texts.delete,
            danger: true,
        });
        if (!confirmed) {
            return;
        }
        try {
            await deleteRecords(this.orm, this.props.resModel, [resId]);
        } catch (error) {
            notify(this.notification, error?.data?.message || error?.message || this.texts.actionFailed, {
                type: "danger",
                sticky: true,
            });
            return;
        }
        await this.reloadCollection();
    };

    /**
     * 双击一行进入表单: 同一行两次点击的间隔不超过 DOUBLE_TAP_DELAY 视为双击.
     * 触摸设备上的双击不一定产生 dblclick 事件, 所以这里根据 click 判断, 鼠标与触摸都适用.
     */
    onRowClick(ev) {
        const id = Number(ev.currentTarget.dataset.id);
        const now = Date.now();
        const isDoubleClick = this.lastRowClick.id === id && now - this.lastRowClick.time <= DOUBLE_TAP_DELAY;
        this.lastRowClick = isDoubleClick ? { id: null, time: 0 } : { id, time: now };
        if (isDoubleClick) {
            this.props.onSelect(id);
        }
    }

    /** 下拉刷新时的提示文字 */
    get pullText() {
        return pullLabel(this.pull.state);
    }
}

mobileViewRegistry.add("list", MobileListView);

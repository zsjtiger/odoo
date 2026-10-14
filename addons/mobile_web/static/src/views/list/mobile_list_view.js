import { Component, onWillStart, onWillUpdateProps, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames, isHiddenColumn, splitColumns } from "@mobile_web/views/arch";
import { getFieldWidget } from "@mobile_web/views/fields/index";
import { MobileRecordModel } from "@mobile_web/views/record_model";
import { RecordCollection } from "@mobile_web/views/record_list";
import { hasDisplayValue } from "@mobile_web/views/fields/field_utils";
import { useInfiniteScroll } from "@mobile_web/views/infinite_scroll";
import { _t } from "@web/core/data/l10n/translation";

/**
 * 移动端列表视图: 每行一张卡片式的行, 第一列作为标题, 后面的列作为副标题
 *
 * 点击整行进入表单; 底部"加载更多"分页, 避免一次加载过多数据
 */
// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    refresh: _t("Refresh"),
    loadFailed: _t("Failed to load, please try again"),
    noRecords: _t("No records"),
    loading: _t("Loading…"),
};

export class MobileListView extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.MobileListView">
            <div class="m_list_view">
                <div class="m_list_meta">
                    <button type="button" class="m_link_button" t-on-click="this.onRefresh"><t t-esc="this.texts.refresh"/></button>
                </div>
                <ul class="m_list">
                    <li t-foreach="this.collection.state.records" t-as="record" t-key="record.resId">
                        <button type="button" class="m_list_row" t-att-data-id="record.resId" t-on-click="this.onRowClick">
                            <div class="m_list_primary">
                                <t t-if="this.primary" t-component="this.getWidget(this.primary)" t-props="this.cellProps(this.primary, record)"/>
                            </div>
                            <div class="m_list_secondary" t-if="this.secondary.length">
                                <t t-foreach="this.secondary" t-as="column" t-key="column.name">
                                    <span class="m_list_cell" t-if="this.hasValue(column, record)"><t t-component="this.getWidget(column)" t-props="this.cellProps(column, record)"/></span>
                                </t>
                            </div>
                        </button>
                    </li>
                </ul>
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

    setup() {
        const node = parseArch(this.props.arch);
        const columns = node.children.filter((c) => c.tag === "field" && c.attrs.name && !isHiddenColumn(c));
        const { primary, secondary } = splitColumns(columns.map((c) => this.column(c)));
        this.primary = primary;
        this.secondary = secondary;
        const fieldNames = [...collectFieldNames(node)];
        this.collection = new RecordCollection(this.makeModel(), fieldNames);
        onWillStart(() => this.collection.reload(this.props.domain));
        this.infinite = useInfiniteScroll(this.collection);
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.collection.domain)) {
                return this.collection.reload(nextProps.domain).then(() => this.infinite.recheck());
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

    getWidget(column) {
        return getFieldWidget(column.attrs, column.field);
    }

    cellProps(column, record) {
        return {
            name: column.name,
            field: column.field,
            record,
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

    onRowClick(ev) {
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    onRefresh() {
        return this.collection.reload();
    }
}

mobileViewRegistry.add("list", MobileListView);

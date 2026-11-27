import { xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { hasDisplayValue } from "@mobile_web/fields/field_utils";
import { MobileRecord } from "@mobile_web/views/record";
import { One2manyField } from "@mobile_web/fields/relational_fields";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 通用时间线 (一对多的 widget="timeline"): 明细按日期倒序显示为时间线.
 * 日期取明细列表视图中标记为 mobile_date 的列, 没有标记时取第一个日期/日期时间列;
 * 标题为第一列 (mobile_title 或文本列), 其余列作为卡片中的内容行.
 * 点击节点在明细编辑页中编辑, 与一对多一致.
 */
export class TimelineField extends One2manyField {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.TimelineField">
            <ol t-if="this.state.rows.length" class="m_timeline">
                <li t-foreach="this.state.rows" t-as="row" t-key="row.id" class="m_timeline_item"
                    t-att-data-id="row.id" t-on-click="this.onRowClick">
                    <div class="m_timeline_date">
                        <t t-if="row.date" t-component="row.date.widget" t-props="row.date.props"/>
                    </div>
                    <span class="m_timeline_dot" aria-hidden="true"/>
                    <div class="m_timeline_card">
                        <div class="m_timeline_title">
                            <t t-if="row.primary" t-component="row.primary.widget" t-props="row.primary.props"/>
                        </div>
                        <div t-foreach="row.secondary" t-as="cell" t-key="cell.name" class="m_timeline_line">
                            <t t-if="cell.hasValue" t-component="cell.widget" t-props="cell.props"/>
                        </div>
                    </div>
                </li>
            </ol>
            <ul t-else="" class="m_one2many_list">
                <li t-if="!this.props.readonly and !this.state.pairs.length and this.state.schemaReady" class="m_field_empty"><t t-esc="this.texts.none"/></li>
            </ul>
            <button t-if="!this.props.readonly and this.state.schemaReady" type="button" class="m_one2many_add" t-on-click="this.addLine">
                <t t-esc="this.texts.addLine"/>
            </button>
            <LineEditor t-if="this.state.editing"
                title="this.state.editing.title"
                resModel="this.props.field.relation"
                blocks="this.state.editing.blocks"
                record="this.state.editing.record"
                fields="this.schema.fields"
                onSave="this.saveLine"
                onCancel="this.cancelLine"
                onDelete="this.deleteLine"/>
        </t>
    `;

    /** 日期列: 优先 mobile_date 标记, 否则第一个日期/日期时间列 */
    get dateColumn() {
        const columns = this.schema?.columns || [];
        return (
            columns.find((c) => (c.attrs.class || "").split(/\s+/).includes("mobile_date")) ||
            columns.find((c) => ["date", "datetime"].includes(c.field.type)) ||
            null
        );
    }

    refreshRows() {
        if (!this.schema || !this.state.pairs.length || this.props.compact) {
            this.state.rows = [];
            return;
        }
        const { fields, primary, secondary, relation } = this.schema;
        const dateColumn = this.dateColumn;
        const rows = this.state.pairs
            .filter(([id]) => id < 0 || this.state.lines[id])
            .map(([id]) => {
                const data = this.lineData(id);
                const record = new MobileRecord(fields, id, data);
                const dateValue = dateColumn ? data[dateColumn.name] : undefined;
                return {
                    id,
                    sortKey: hasDisplayValue(dateValue) ? String(dateValue) : "",
                    date: dateColumn && hasDisplayValue(dateValue) ? this.cell(dateColumn, record, relation) : null,
                    primary: primary && this.cell(primary, record, relation),
                    secondary: secondary
                        .filter((column) => column !== primary && column !== dateColumn)
                        .map((column) => this.cell(column, record, relation)),
                };
            });
        // 日期倒序, 没有日期的记录排在最后
        rows.sort((a, b) => (a.sortKey === b.sortKey ? 0 : a.sortKey < b.sortKey ? 1 : -1));
        this.state.rows = rows;
    }
}
mobileFieldRegistry.add("timeline", TimelineField);

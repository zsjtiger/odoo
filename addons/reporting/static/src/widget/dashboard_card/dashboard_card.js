import { xml } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { formatInteger } from "@web/views/fields/formatters";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

/**
 * 卡片视图: 每个数据项一张卡片, 显示名称与合计值; 点击卡片打开对应的记录列表.
 * options.column: 每行的卡片数 (不设置时卡片平分剩余宽度).
 */
export class DashBoardCardWidget extends DashBoardCommonWidget {
    static template = xml`
        <t t-name="reporting.DashBoardCardWidget">
            <div class="snow_mdm_dashboard_chart_container">
                <t t-if="this.showLoading"><t t-out="this.texts.loading"/></t>
                <div t-else="" class="snow_mdm_dashboard_card_container">
                    <t t-foreach="this.dashboardData" t-as="item" t-key="item.name">
                        <div class="snow_mdm_dashboard_card" t-att-style="this.cardStyle"
                             t-att-data-data-name="item.name" t-on-click="() => this.onItemClick(item.name)">
                            <h4 class="snow_mdm_dashboard_card_title"><t t-out="item.name"/></h4>
                            <h5 class="snow_mdm_dashboard_card_value"><t t-out="this.formatValue(item.value)"/></h5>
                        </div>
                    </t>
                    <t t-foreach="this.placeholders" t-as="index" t-key="index">
                        <div class="snow_mdm_dashboard_card snow_mdm_dashboard_card_placeholder" t-att-style="this.cardStyle"/>
                    </t>
                </div>
            </div>
        </t>
    `;

    renderChart() {}

    get dashboardData() {
        return this._mergeDashboardDataDimensions(this._getDashboardData());
    }

    get columnCount() {
        return parseInt(this.props.options.column) || 0;
    }

    get cardStyle() {
        if (this.columnCount) {
            return `flex-basis: calc(${100 / this.columnCount}% - 20px);`;
        }
        return "flex-grow: 1;";
    }

    /** 补齐最后一行, 使卡片对齐 */
    get placeholders() {
        const count = this.dashboardData.length;
        if (!this.columnCount) {
            return [];
        }
        const missing = Math.ceil(count / this.columnCount) * this.columnCount - count;
        return Array.from({ length: missing }, (_, i) => i);
    }

    formatValue(value) {
        return value ? formatInteger(value) : "";
    }

    onItemClick(name) {
        this._doPageAction(name, null);
    }
}

registry.category("fields").add("board_dashboard_card", {
    component: DashBoardCardWidget,
    supportedTypes: ["text", "char"],
});

import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

export class DashBoardBarWidget extends DashBoardCommonWidget {
    getChartOption() {
        return {
            legend: {},
            tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
            dataset: this._getEchartsDataSet(),
            series: this._getEchartsSeries("bar"),
            ...this._getAxis(),
        };
    }

    _getAxis() {
        const categoryAxis = {
            type: "category",
            axisLabel: { interval: 0, rotate: 45 },
            splitLine: { show: true },
        };
        const valueAxis = {
            type: "value",
            minorSplitLine: { show: true },
            axisLabel: { formatter: (v) => this._formatValueHumanReadble(v) },
        };
        if (this.props.options.direction === "horizontal") {
            return { xAxis: valueAxis, yAxis: categoryAxis };
        }
        return { xAxis: categoryAxis, yAxis: valueAxis };
    }
}

registry.category("fields").add("board_dashboard_bar", {
    component: DashBoardBarWidget,
    supportedTypes: ["text", "char"],
});

import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

export class DashBoardLineWidget extends DashBoardCommonWidget {
    getChartOption() {
        return {
            legend: {},
            tooltip: { trigger: "axis" },
            dataset: this._getEchartsDataSet(),
            xAxis: {
                type: "category",
                axisLabel: { interval: 0, rotate: 45 },
                splitLine: { show: true },
            },
            yAxis: {
                type: "value",
                minorSplitLine: { show: true },
                axisLabel: { formatter: (v) => this._formatValueHumanReadble(v) },
            },
            series: this._getEchartsSeries("line"),
        };
    }
}

registry.category("fields").add("board_dashboard_line", {
    component: DashBoardLineWidget,
    supportedTypes: ["text", "char"],
});

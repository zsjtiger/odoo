import { registry } from "@web/core/framework/registry";
import { formatInteger } from "@web/views/fields/formatters";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

export class DashBoardPieWidget extends DashBoardCommonWidget {
    getChartOption() {
        const series = this._getEchartsSeries("pie").map((s) => ({
            ...s,
            center: ["50%", "60%"],
            label: { show: false },
            labelLine: { show: false },
        }));
        return {
            tooltip: {
                trigger: "item",
                formatter: (param) => {
                    const value = param.data.value ? formatInteger(param.data.value) : null;
                    return `${param.data.name} <br/> ${value}`;
                },
            },
            legend: { type: "scroll" },
            dataset: this._getEchartsDataSet(),
            series,
        };
    }
}

registry.category("fields").add("board_dashboard_pie", {
    component: DashBoardPieWidget,
    supportedTypes: ["text", "char"],
});

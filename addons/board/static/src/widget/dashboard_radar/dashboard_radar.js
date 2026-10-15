import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

export class DashBoardRadarWidget extends DashBoardCommonWidget {
    getChartOption() {
        const dashboardData = this._getDashboardData();
        const dimensions = Object.keys(dashboardData[0] || {}).filter((key) => key !== "name");

        // 雷达图的最大值: 均值 + 2 倍标准差
        const allValues = [];
        dashboardData.forEach((item) => {
            dimensions.forEach((dim) => {
                if (typeof item[dim] === "number") {
                    allValues.push(item[dim]);
                }
            });
        });
        const count = allValues.length || 1;
        const mean = allValues.reduce((a, b) => a + b, 0) / count;
        const variance = allValues.map((v) => (v - mean) ** 2).reduce((a, b) => a + b, 0) / count;
        const maxValue = mean + 2 * Math.sqrt(variance);

        return {
            legend: {
                data: dimensions,
                type: "scroll",
                orient: "vertical",
                left: 2,
                bottom: 2,
            },
            tooltip: { trigger: "item" },
            radar: {
                indicator: dashboardData.map((item) => ({ name: item.name, max: maxValue })),
            },
            series: [
                {
                    type: "radar",
                    data: dimensions.map((dim) => ({
                        name: dim,
                        value: dashboardData.map((item) => item[dim] || 0),
                    })),
                },
            ],
        };
    }

    /** 雷达图不支持点击跳转 */
    _handleEchartsChartClick() {}
}

registry.category("fields").add("board_dashboard_radar", {
    component: DashBoardRadarWidget,
    supportedTypes: ["text", "char"],
});

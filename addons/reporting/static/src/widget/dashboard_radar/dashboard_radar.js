import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

export class DashBoardRadarWidget extends DashBoardCommonWidget {
    getChartOption() {
        const dashboardData = this._getDashboardData();
        // 维度取所有数据项的并集: 不同 name 可能只有部分维度
        const dimensionSet = new Set();
        dashboardData.forEach((item) => Object.keys(item).forEach((key) => key !== "name" && dimensionSet.add(key)));
        const dimensions = [...dimensionSet];

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

        // 雷达的坐标轴是维度(如 Quality / Price), 每个 name(如 Alpha / Beta) 画成一个多边形
        return {
            legend: {
                data: dashboardData.map((item) => item.name),
                type: "scroll",
                orient: "vertical",
                left: 2,
                bottom: 2,
            },
            tooltip: { trigger: "item" },
            radar: {
                indicator: dimensions.map((dim) => ({ name: dim, max: maxValue })),
            },
            series: [
                {
                    type: "radar",
                    data: dashboardData.map((item) => ({
                        name: item.name,
                        value: dimensions.map((dim) => item[dim] || 0),
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

import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

const POINTER_ICON =
    "path://M2.9,0.7L2.9,0.7c1.4,0,2.6,1.2,2.6,2.6v115c0,1.4-1.2,2.6-2.6,2.6l0,0c-1.4,0-2.6-1.2-2.6-2.6V3.3C0.3,1.9,1.4,0.7,2.9,0.7z";

export class DashBoardGaugeWidget extends DashBoardCommonWidget {
    getChartOption() {
        const dashboardData = this._mergeDashboardDataDimensions(this._getDashboardData());
        const el = this.chartRef();
        const minSize = Math.min(el?.clientHeight || 0, el?.clientWidth || 0);
        const valueTotal = dashboardData.reduce((sum, item) => sum + item.value, 0);
        const dataCount = dashboardData.length;

        const gaugeData = dashboardData.map((item, index) => {
            const legendInfo = { title: { fontSize: 11 }, detail: { fontSize: 11 } };
            if (minSize < 200) {
                const gap = 200 / dataCount;
                const offset = `${(index - (dataCount - 1) / 2) * gap}%`;
                legendInfo.title.offsetCenter = ["-250%", offset];
                legendInfo.detail.offsetCenter = ["-150%", offset];
            } else {
                const gap = 200 / dataCount;
                const offset = `${(index - (dataCount - 1) / 2) * gap}%`;
                legendInfo.title.offsetCenter = [offset, "80%"];
                legendInfo.detail.offsetCenter = [offset, "100%"];
            }
            return {
                name: item.name,
                value: parseFloat(((item.value / valueTotal) * 100).toFixed(2)),
                ...legendInfo,
            };
        });

        return {
            series: [
                {
                    name: "value",
                    type: "gauge",
                    anchor: { show: true, showAbove: true, size: 18, itemStyle: { color: "#FAC858" } },
                    progress: { show: true, overlap: true, roundCap: true },
                    pointer: { icon: POINTER_ICON, width: 4, length: "80%", offsetCenter: [0, "8%"] },
                    axisLine: { roundCap: true },
                    data: gaugeData,
                    detail: {
                        width: 20,
                        height: 11,
                        fontSize: 14,
                        color: "#fff",
                        backgroundColor: "inherit",
                        borderRadius: 3,
                        formatter: "{value}%",
                    },
                    axisLabel: { show: minSize >= 200 },
                },
            ],
        };
    }
}

registry.category("fields").add("board_dashboard_gauge", {
    component: DashBoardGaugeWidget,
    supportedTypes: ["text", "char"],
});

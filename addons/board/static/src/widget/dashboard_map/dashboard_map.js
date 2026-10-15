import { registry } from "@web/core/framework/registry";
import { formatInteger } from "@web/views/fields/formatters";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

const GEO_URL = "/board/static/public/cn_geo.json";

export class DashBoardMapWidget extends DashBoardCommonWidget {
    geoLoaded = false;

    /** 地图需要先加载中国地图的 geo json, 再绘制 */
    renderChart() {
        if (this.showLoading) {
            return;
        }
        if (!this.geoLoaded) {
            this._loadGeo().then(() => super.renderChart());
            return;
        }
        super.renderChart();
    }

    async _loadGeo() {
        if (this.geoLoaded || !window.echarts) {
            return;
        }
        const response = await fetch(GEO_URL);
        window.echarts.registerMap("CN", await response.json());
        this.geoLoaded = true;
    }

    getChartOption() {
        return {
            tooltip: {
                trigger: "item",
                formatter: (param) => {
                    const value = param.data.value ? formatInteger(param.data.value) : null;
                    return `${param.data.name} <br/> ${value}`;
                },
            },
            visualMap: {
                min: 0,
                max: 100000,
                text: ["High", "Low"],
                realtime: false,
                calculable: true,
                inRange: { color: ["lightskyblue", "yellow", "orangered"] },
            },
            series: [
                {
                    // 系列名必须为 value 或后端数据的 category 值, 点击时据此判断维度
                    name: "value",
                    type: "map",
                    map: "CN",
                    roam: true,
                    label: { show: false },
                    zoom: 1.2,
                    scaleLimit: { min: 1, max: 15 },
                    data: this._fieldData,
                },
            ],
        };
    }
}

registry.category("fields").add("board_dashboard_map", {
    component: DashBoardMapWidget,
    supportedTypes: ["text", "char"],
});

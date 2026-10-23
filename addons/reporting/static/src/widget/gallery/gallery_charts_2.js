import { registry } from "@web/core/framework/registry";
import { GalleryChartWidget } from "./gallery_charts";

/**
 * 第二批扩展图表: 环形图/饼图变体与散点图.
 * 饼图类沿用 category 作为扇区 (每个 category 的合计).
 * 散点图的数据项 value 为 [x, y]; category 为分组 (没有分组时为一组 "value").
 */

/** 每个 category 的合计, 用于饼图与环形图 */
function sliceTotals(widget) {
    return widget._matrix().series.map((s) => ({ name: s.name, value: s.values.reduce((a, b) => a + b, 0) }));
}

/** 散点数据: {series: [{name, points: [[x, y], ...]}]} */
function pointSeries(widget) {
    const groups = new Map();
    for (const item of widget._fieldData) {
        const key = item.category ?? "value";
        const [x, y] = Array.isArray(item.value) ? item.value : [groups.get(key)?.length ?? 0, item.value];
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key).push([x, y]);
    }
    return [...groups].map(([name, points]) => ({ name, points }));
}

/** 线性回归 y = a + b x */
function linearFit(points) {
    const n = points.length;
    const mx = points.reduce((s, p) => s + p[0], 0) / n;
    const my = points.reduce((s, p) => s + p[1], 0) / n;
    const sxx = points.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
    const sxy = points.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0);
    const b = sxx ? sxy / sxx : 0;
    return { a: my - b * mx, b };
}

/** 指数回归 y = a e^(b x) (对 y 取对数做线性回归), y 必须为正 */
function exponentialFit(points) {
    const logs = points.filter((p) => p[1] > 0).map((p) => [p[0], Math.log(p[1])]);
    const { a, b } = linearFit(logs);
    return { a: Math.exp(a), b };
}

export class DashBoardDoughnutWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { type: "scroll", bottom: 0 },
            series: [
                {
                    type: "pie",
                    radius: ["40%", "70%"],
                    center: ["50%", "45%"],
                    data: sliceTotals(this),
                    label: { show: false },
                },
            ],
        };
    }
}

export class DashBoardDoughnutRoundedWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { type: "scroll", bottom: 0 },
            series: [
                {
                    type: "pie",
                    radius: ["40%", "70%"],
                    center: ["50%", "45%"],
                    padAngle: 3,
                    itemStyle: { borderRadius: 8 },
                    data: sliceTotals(this),
                    label: { show: false },
                },
            ],
        };
    }
}

export class DashBoardHalfDoughnutWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { type: "scroll", bottom: 0 },
            series: [
                {
                    type: "pie",
                    radius: ["40%", "70%"],
                    center: ["50%", "70%"],
                    startAngle: 180,
                    endAngle: 360,
                    data: sliceTotals(this),
                    label: { show: true, formatter: "{b}" },
                },
            ],
        };
    }
}

export class DashBoardPiePadAngleWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { type: "scroll", bottom: 0 },
            series: [
                {
                    type: "pie",
                    radius: "70%",
                    center: ["50%", "45%"],
                    padAngle: 5,
                    itemStyle: { borderRadius: 5 },
                    data: sliceTotals(this),
                    label: { show: false },
                },
            ],
        };
    }
}

/** 基础散点图 */
export class DashBoardScatterWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { bottom: 0 },
            grid: { left: 50, right: 20, top: 30, bottom: 50 },
            xAxis: { type: "value", scale: true },
            yAxis: { type: "value", scale: true },
            series: pointSeries(this).map((s) => ({ type: "scatter", name: s.name, data: s.points, symbolSize: 10 })),
        };
    }
}

/** 安斯库姆四重奏: 四个子图, 每个子图一个 category, 带回归线 */
export class DashBoardScatterQuartetWidget extends GalleryChartWidget {
    getChartOption() {
        const groups = pointSeries(this);
        const grids = [];
        const xAxis = [];
        const yAxis = [];
        const series = [];
        groups.forEach((group, index) => {
            const col = index % 2;
            const row = Math.floor(index / 2);
            grids.push({ left: `${8 + col * 48}%`, width: "40%", top: `${12 + row * 44}%`, height: "32%" });
            xAxis.push({ type: "value", gridIndex: index, min: 0, max: 20, name: group.name });
            yAxis.push({ type: "value", gridIndex: index, min: 2, max: 14 });
            const fit = linearFit(group.points);
            series.push({ type: "scatter", xAxisIndex: index, yAxisIndex: index, name: group.name, data: group.points });
            series.push({
                type: "line",
                xAxisIndex: index,
                yAxisIndex: index,
                name: `${group.name} fit`,
                showSymbol: false,
                data: [[0, fit.a], [20, fit.a + fit.b * 20]],
            });
        });
        return { tooltip: { trigger: "item" }, grid: grids, xAxis, yAxis, series };
    }
}

/** 聚类散点: 每个簇一种颜色, 图例可切换 */
export class DashBoardScatterClusterWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            legend: { type: "scroll", orient: "vertical", right: 0, top: 20 },
            grid: { left: 50, right: 120, top: 30, bottom: 40 },
            xAxis: { type: "value", scale: true },
            yAxis: { type: "value", scale: true },
            series: pointSeries(this).map((s) => ({ type: "scatter", name: s.name, data: s.points, symbolSize: 9 })),
        };
    }
}

/** 聚类过程可视化: 所有点为灰色, 底部滑块可以缩放查看 */
export class DashBoardScatterClusterProcessWidget extends GalleryChartWidget {
    getChartOption() {
        const points = this._fieldData.map((item) => (Array.isArray(item.value) ? item.value : [0, item.value]));
        return {
            tooltip: { trigger: "item" },
            grid: { left: 50, right: 20, top: 20, bottom: 60 },
            dataZoom: [{ type: "inside", xAxisIndex: 0 }, { type: "slider", xAxisIndex: 0, bottom: 10, height: 16 }],
            xAxis: { type: "value", scale: true },
            yAxis: { type: "value", scale: true },
            series: [{ type: "scatter", name: "points", data: points, symbolSize: 9, itemStyle: { color: "#9a9a9a" } }],
        };
    }
}

/** 指数回归: 散点与拟合曲线 y = a e^(bx) */
export class DashBoardScatterRegressionWidget extends GalleryChartWidget {
    getChartOption() {
        const points = pointSeries(this)[0]?.points || [];
        const { a, b } = exponentialFit(points);
        const xs = points.map((p) => p[0]);
        const min = Math.min(...xs);
        const max = Math.max(...xs);
        const curve = Array.from({ length: 41 }, (_, i) => {
            const x = min + ((max - min) * i) / 40;
            return [x, a * Math.exp(b * x)];
        });
        return {
            tooltip: { trigger: "item" },
            grid: { left: 60, right: 20, top: 30, bottom: 40 },
            xAxis: { type: "value", scale: true },
            yAxis: { type: "value", scale: true },
            series: [
                { type: "scatter", name: "data", data: points, symbolSize: 9 },
                { type: "line", name: "fit", data: curve, showSymbol: false, smooth: true },
            ],
        };
    }
}

/** 涟漪特效散点: 数据点带有涟漪效果 */
export class DashBoardScatterEffectWidget extends GalleryChartWidget {
    getChartOption() {
        return {
            tooltip: { trigger: "item" },
            grid: { left: 50, right: 20, top: 30, bottom: 40 },
            xAxis: { type: "value", scale: true },
            yAxis: { type: "value", scale: true },
            series: pointSeries(this).map((s, index) => ({
                type: "effectScatter",
                name: s.name,
                data: s.points,
                symbolSize: 8,
                rippleEffect: { brushType: "stroke", scale: index === 0 ? 3 : 2.2 },
                itemStyle: { shadowBlur: 6, shadowColor: "rgba(0, 0, 0, 0.2)" },
            })),
        };
    }
}

export const GALLERY_WIDGETS_2 = {
    board_dashboard_doughnut: DashBoardDoughnutWidget,
    board_dashboard_doughnut_rounded: DashBoardDoughnutRoundedWidget,
    board_dashboard_doughnut_half: DashBoardHalfDoughnutWidget,
    board_dashboard_pie_pad_angle: DashBoardPiePadAngleWidget,
    board_dashboard_scatter: DashBoardScatterWidget,
    board_dashboard_scatter_quartet: DashBoardScatterQuartetWidget,
    board_dashboard_scatter_cluster: DashBoardScatterClusterWidget,
    board_dashboard_scatter_cluster_process: DashBoardScatterClusterProcessWidget,
    board_dashboard_scatter_regression: DashBoardScatterRegressionWidget,
    board_dashboard_scatter_effect: DashBoardScatterEffectWidget,
};

for (const [name, widget] of Object.entries(GALLERY_WIDGETS_2)) {
    registry.category("fields").add(name, {
        component: widget,
        supportedTypes: ["text", "char"],
    });
}

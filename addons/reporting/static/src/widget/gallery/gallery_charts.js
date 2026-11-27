import { registry } from "@web/core/framework/registry";
import { DashBoardCommonWidget } from "../common/dashboard_widget";

/**
 * 扩展图表 (与 echarts 示例库的样式对应). 数据格式与其它仪表盘图表相同:
 *   {name, value, category, filter_domain}
 * 没有 category 时只有一个系列 (名为 value); 有 category 时每个 category 是一个系列.
 */
export class GalleryChartWidget extends DashBoardCommonWidget {
    /** 名称 (横轴 / 角度) 与系列数值; 某个名称在某个系列中没有数据时记为 0 */
    _matrix() {
        const names = [];
        const categories = [];
        for (const item of this._fieldData) {
            if (!names.includes(item.name)) {
                names.push(item.name);
            }
            if (item.category !== null && !categories.includes(item.category)) {
                categories.push(item.category);
            }
        }
        const lookup = new Map(this._fieldData.map((d) => [`${d.name}\u0000${d.category}`, d.value]));
        const series = (categories.length ? categories : [null]).map((category) => ({
            name: category ?? "value",
            category,
            values: names.map((name) => lookup.get(`${name}\u0000${category}`) ?? 0),
        }));
        return { names, series };
    }

    _lineSeries(extra = () => ({})) {
        return this._matrix().series.map((s) => ({ type: "line", name: s.name, data: s.values, ...extra(s) }));
    }

    _categoryAxis(names) {
        return {
            type: "category",
            data: names,
            axisLabel: { interval: 0, rotate: 45 },
            splitLine: { show: true },
        };
    }

    _valueAxis() {
        return {
            type: "value",
            minorSplitLine: { show: true },
            axisLabel: { formatter: (v) => this._formatValueHumanReadble(v) },
        };
    }
}

/** 平滑折线图 */
export class DashBoardSmoothLineWidget extends GalleryChartWidget {
    getChartOption() {
        const { names } = this._matrix();
        return {
            legend: {},
            tooltip: { trigger: "axis" },
            grid: { left: 50, right: 20, top: 40, bottom: 50 },
            xAxis: this._categoryAxis(names),
            yAxis: this._valueAxis(),
            series: this._lineSeries(() => ({ smooth: true })),
        };
    }
}

/** 堆叠折线图: 系列逐层相加 */
export class DashBoardStackedLineWidget extends GalleryChartWidget {
    getChartOption() {
        const { names } = this._matrix();
        return {
            legend: {},
            tooltip: { trigger: "axis" },
            grid: { left: 50, right: 20, top: 40, bottom: 50 },
            xAxis: this._categoryAxis(names),
            yAxis: this._valueAxis(),
            series: this._lineSeries(() => ({ stack: "total", symbol: "circle" })),
        };
    }
}

/** 标注折线图: 每个系列标出最高、最低值, 并画出平均线 */
export class DashBoardMarkedLineWidget extends GalleryChartWidget {
    getChartOption() {
        const { names } = this._matrix();
        return {
            legend: {},
            tooltip: { trigger: "axis" },
            grid: { left: 50, right: 70, top: 40, bottom: 50 },
            xAxis: this._categoryAxis(names),
            yAxis: this._valueAxis(),
            series: this._lineSeries(() => ({
                markPoint: { data: [{ type: "max", name: "Max" }, { type: "min", name: "Min" }] },
                markLine: { data: [{ type: "average", name: "Avg" }] },
            })),
        };
    }
}

/** 饼图与折线图联动: 上方饼图是各名称的合计, 下方折线图是同一份数据的各系列 */
export class DashBoardPieLineWidget extends GalleryChartWidget {
    getChartOption() {
        const { names, series } = this._matrix();
        // 饼图按系列 (category) 合计, 折线图按名称 (横轴) 展示各系列的变化
        const totals = series.map((s) => ({ name: s.name, value: s.values.reduce((a, b) => a + b, 0) }));
        return {
            tooltip: { trigger: "item" },
            legend: { data: series.map((s) => s.name), bottom: 0, right: 0, orient: "vertical" },
            series: [
                {
                    type: "pie",
                    radius: "55%",
                    center: ["24%", "50%"],
                    data: totals,
                    label: { show: true, formatter: "{b}: {d}%" },
                },
                ...series.map((s) => ({ type: "line", name: s.name, data: s.values, smooth: true })),
            ],
            grid: { left: "50%", right: 120, top: 30, bottom: 40 },
            xAxis: this._categoryAxis(names),
            yAxis: this._valueAxis(),
        };
    }
}

/**
 * 极坐标柱状图: radial (径向柱, 名称在半径轴), tangential (切向柱, 名称在角度轴),
 * end_angle (扇形玫瑰图, 角度轴只到 endAngle)
 */
export class DashBoardPolarBarWidget extends GalleryChartWidget {
    static layout = "radial";

    getChartOption() {
        const { names, series } = this._matrix();
        const layout = this.constructor.layout;
        const endAngle = this.props.options.end_angle ?? (layout === "end_angle" ? 270 : 360);
        const categoryAxis = { type: "category", data: names };
        const valueAxis = { type: "value" };
        const polarAxes =
            layout === "tangential"
                ? { angleAxis: { ...categoryAxis }, radiusAxis: valueAxis }
                : { angleAxis: { type: "value", startAngle: 90, endAngle }, radiusAxis: { ...categoryAxis } };
        return {
            legend: series.length > 1 ? { bottom: 0 } : undefined,
            tooltip: { trigger: "item" },
            polar: { center: ["50%", "48%"], radius: layout === "tangential" ? ["18%", "70%"] : ["12%", "70%"] },
            ...polarAxes,
            series: series.map((s) => ({
                type: "bar",
                coordinateSystem: "polar",
                name: s.name,
                stack: series.length > 1 ? "total" : undefined,
                data: s.values,
                label: { show: true, position: layout === "end_angle" ? "inside" : "middle" },
            })),
        };
    }
}

export class DashBoardPolarRadialWidget extends DashBoardPolarBarWidget {
    static layout = "radial";
}

export class DashBoardPolarTangentialWidget extends DashBoardPolarBarWidget {
    static layout = "tangential";
}

export class DashBoardPolarEndAngleWidget extends DashBoardPolarBarWidget {
    static layout = "end_angle";
}

/** 横向柱状图 (数据的名称在纵轴) */
export class DashBoardHorizontalBarWidget extends GalleryChartWidget {
    getChartOption() {
        const { names, series } = this._matrix();
        return {
            legend: {},
            tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
            xAxis: this._valueAxis(),
            yAxis: { type: "category", data: names, axisLabel: { interval: 0 } },
            series: series.map((s) => ({ type: "bar", name: s.name, data: s.values })),
        };
    }
}

/**
 * 断轴柱状图: 数值相差很大时, 把纵轴分成上下两段, 中间留出断开的空隙.
 * 断开位置取最大相邻数值比超过 4 倍的那一处; 没有这样的差距时画成普通柱状图.
 */
export class DashBoardAxisBreakBarWidget extends GalleryChartWidget {
    getChartOption() {
        const { names, series } = this._matrix();
        const values = [...new Set(series.flatMap((s) => s.values))].filter((v) => v > 0).sort((a, b) => a - b);
        // 找相邻数值之间比值最大的那一处, 比值超过 4 才断开
        let bestRatio = 4;
        let gapLow = null;
        let gapHigh = null;
        for (let i = 1; i < values.length; i++) {
            const ratio = values[i] / values[i - 1];
            if (ratio > bestRatio) {
                bestRatio = ratio;
                gapLow = values[i - 1];
                gapHigh = values[i];
            }
        }
        const lowTop = gapLow === null ? null : gapLow * 1.2;
        const highBottom = gapHigh === null ? null : gapHigh * 0.8;
        const max = values.length ? values[values.length - 1] * 1.05 : 1;
        if (lowTop === null) {
            return {
                legend: {},
                tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
                xAxis: this._categoryAxis(names),
                yAxis: this._valueAxis(),
                series: series.map((s) => ({ type: "bar", name: s.name, data: s.values })),
            };
        }
        const bars = (xIndex) =>
            series.map((s) => ({ type: "bar", name: s.name, data: s.values, xAxisIndex: xIndex, yAxisIndex: xIndex }));
        return {
            legend: { data: series.map((s) => s.name), bottom: 0 },
            tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
            grid: [
                { left: 60, right: 20, top: 30, height: "32%" },
                { left: 60, right: 20, top: "58%", bottom: 60 },
            ],
            xAxis: [
                { ...this._categoryAxis(names), gridIndex: 0, axisLabel: { show: false } },
                { ...this._categoryAxis(names), gridIndex: 1 },
            ],
            yAxis: [
                { type: "value", gridIndex: 0, min: highBottom, max, axisLabel: { formatter: (v) => this._formatValueHumanReadble(v) } },
                { type: "value", gridIndex: 1, min: 0, max: lowTop, axisLabel: { formatter: (v) => this._formatValueHumanReadble(v) } },
            ],
            series: [...bars(0), ...bars(1)],
        };
    }
}

/** 渐变色柱状图: 柱子带渐变色与背景阴影, 可拖动底部滑块缩放 */
export class DashBoardGradientBarWidget extends GalleryChartWidget {
    getChartOption() {
        const { names, series } = this._matrix();
        return {
            tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
            legend: series.length > 1 ? {} : undefined,
            grid: { left: 50, right: 20, top: 40, bottom: 70 },
            dataZoom: [{ type: "inside" }, { type: "slider", bottom: 10, height: 18 }],
            xAxis: this._categoryAxis(names),
            yAxis: this._valueAxis(),
            series: series.map((s) => ({
                type: "bar",
                name: s.name,
                data: s.values,
                showBackground: true,
                backgroundStyle: { color: "rgba(180, 190, 200, 0.2)" },
                itemStyle: {
                    color: {
                        type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [{ offset: 0, color: "#4c8dff" }, { offset: 1, color: "#b3d4ff" }],
                    },
                    shadowBlur: 6,
                    shadowColor: "rgba(0, 0, 0, 0.15)",
                },
                label: { show: true, position: "top" },
            })),
        };
    }
}

// 每个扩展图表对应一个部件名 (与 reporting 视图中的 board_dashboard_* 一致)
export const GALLERY_WIDGETS = {
    board_dashboard_smooth_line: DashBoardSmoothLineWidget,
    board_dashboard_stacked_line: DashBoardStackedLineWidget,
    board_dashboard_marked_line: DashBoardMarkedLineWidget,
    board_dashboard_pie_line: DashBoardPieLineWidget,
    board_dashboard_polar_radial: DashBoardPolarRadialWidget,
    board_dashboard_polar_tangential: DashBoardPolarTangentialWidget,
    board_dashboard_polar_end_angle: DashBoardPolarEndAngleWidget,
    board_dashboard_bar_horizontal: DashBoardHorizontalBarWidget,
    board_dashboard_bar_axis_break: DashBoardAxisBreakBarWidget,
    board_dashboard_bar_gradient: DashBoardGradientBarWidget,
};

for (const [name, widget] of Object.entries(GALLERY_WIDGETS)) {
    registry.category("fields").add(name, {
        component: widget,
        supportedTypes: ["text", "char"],
    });
}

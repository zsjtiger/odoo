import { describe, expect, test } from "@odoo/hoot";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import {
    DashBoardDoughnutWidget,
    DashBoardHalfDoughnutWidget,
    DashBoardPiePadAngleWidget,
    DashBoardScatterEffectWidget,
    DashBoardScatterQuartetWidget,
    DashBoardScatterRegressionWidget,
    DashBoardScatterWidget,
    GALLERY_WIDGETS_2,
} from "@reporting/widget/gallery/gallery_charts_2";

describe.current.tags("headless");

async function getOption(Widget, data) {
    const widget = await mountWithCleanup(Widget, {
        props: {
            name: "chart",
            readonly: true,
            options: {},
            record: {
                data: { chart: JSON.stringify(data) },
                resModel: "reporting.demo",
                context: {},
                fields: { chart: { type: "text", string: "Chart" } },
            },
        },
    });
    return widget.getChartOption();
}

const SLICES = [
    { name: "Mon", value: 10, category: "A", filter_domain: [] },
    { name: "Tue", value: 20, category: "A", filter_domain: [] },
    { name: "Mon", value: 5, category: "B", filter_domain: [] },
];

test("every second-batch chart has its own widget name", () => {
    expect(Object.keys(GALLERY_WIDGETS_2).length).toBe(10);
});

test("a doughnut shows the total of each category as one slice", async () => {
    const option = await getOption(DashBoardDoughnutWidget, SLICES);
    expect(option.series[0].radius).toEqual(["40%", "70%"]);
    expect(option.series[0].data).toEqual([
        { name: "A", value: 30 },
        { name: "B", value: 5 },
    ]);
});

test("a half doughnut spans the lower half of the circle", async () => {
    const option = await getOption(DashBoardHalfDoughnutWidget, SLICES);
    expect(option.series[0].startAngle).toBe(180);
    expect(option.series[0].endAngle).toBe(360);
});

test("a pie with a pad angle leaves gaps between the slices", async () => {
    const option = await getOption(DashBoardPiePadAngleWidget, SLICES);
    expect(option.series[0].padAngle).toBe(5);
});

test("scatter points are grouped by category, and a point without a category is one group", async () => {
    const grouped = await getOption(DashBoardScatterWidget, [
        { name: "p", value: [1, 2], category: "A", filter_domain: [] },
        { name: "p", value: [2, 3], category: "A", filter_domain: [] },
        { name: "p", value: [3, 1], category: "B", filter_domain: [] },
    ]);
    expect(grouped.series.map((s) => s.name)).toEqual(["A", "B"]);
    expect(grouped.series[0].data).toEqual([[1, 2], [2, 3]]);

    const single = await getOption(DashBoardScatterWidget, [{ name: "p", value: [1, 2], category: null, filter_domain: [] }]);
    expect(single.series[0].name).toBe("value");
});

test("the quartet draws one panel per category, each with a fitted line", async () => {
    const option = await getOption(DashBoardScatterQuartetWidget, [
        { name: "p", value: [0, 1], category: "I", filter_domain: [] },
        { name: "p", value: [2, 3], category: "I", filter_domain: [] },
        { name: "p", value: [0, 1], category: "II", filter_domain: [] },
        { name: "p", value: [2, 3], category: "II", filter_domain: [] },
    ]);
    expect(option.grid.length).toBe(2);
    expect(option.series.filter((s) => s.type === "line").length).toBe(2);
    // 两点都在直线 y = x + 1 上, 拟合线经过 (0, 1) 与 (20, 21)
    const fit = option.series.find((s) => s.type === "line");
    expect(Math.abs((fit.data[0][1]) - (1)) < 10 ** -6).toBe(true);
    expect(Math.abs((fit.data[1][1]) - (21)) < 10 ** -6).toBe(true);
});

test("the exponential regression recovers an exact exponential curve", async () => {
    const points = [1, 2, 3, 4, 5].map((x) => ({ name: "p", value: [x, 2 * Math.exp(0.5 * x)], category: null, filter_domain: [] }));
    const option = await getOption(DashBoardScatterRegressionWidget, points);
    const curve = option.series.find((s) => s.name === "fit").data;
    const last = curve[curve.length - 1];
    expect(Math.abs((last[0]) - (5)) < 10 ** -6).toBe(true);
    expect(Math.abs((last[1]) - (2 * Math.exp(2.5))) < 10 ** -4).toBe(true);
});

test("the effect scatter uses the ripple series type", async () => {
    const option = await getOption(DashBoardScatterEffectWidget, SLICES.map((s) => ({ ...s, value: [s.value, s.value] })));
    expect(option.series.every((s) => s.type === "effectScatter")).toBe(true);
});

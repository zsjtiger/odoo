import { describe, expect, test } from "@odoo/hoot";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import {
    DashBoardAxisBreakBarWidget,
    DashBoardGradientBarWidget,
    DashBoardHorizontalBarWidget,
    DashBoardMarkedLineWidget,
    DashBoardPieLineWidget,
    DashBoardPolarEndAngleWidget,
    DashBoardPolarRadialWidget,
    DashBoardPolarTangentialWidget,
    DashBoardSmoothLineWidget,
    DashBoardStackedLineWidget,
    GALLERY_WIDGETS,
} from "@reporting/widget/gallery/gallery_charts";

describe.current.tags("headless");

async function getOption(Widget, data, options = {}) {
    const widget = await mountWithCleanup(Widget, {
        props: {
            name: "chart",
            readonly: true,
            options,
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

const WEEK = [
    { name: "Mon", value: 10, category: "A", filter_domain: [] },
    { name: "Tue", value: 20, category: "A", filter_domain: [] },
    { name: "Mon", value: 5, category: "B", filter_domain: [] },
    { name: "Tue", value: 8, category: "B", filter_domain: [] },
];

test("every gallery chart has its own widget name", () => {
    expect(Object.keys(GALLERY_WIDGETS).length).toBe(10);
    expect(GALLERY_WIDGETS.board_dashboard_bar_gradient).toBe(DashBoardGradientBarWidget);
});

test("smooth lines are smooth and stacked lines share one stack", async () => {
    const smooth = await getOption(DashBoardSmoothLineWidget, WEEK);
    expect(smooth.series.map((s) => s.name)).toEqual(["A", "B"]);
    expect(smooth.series.every((s) => s.smooth)).toBe(true);
    const stacked = await getOption(DashBoardStackedLineWidget, WEEK);
    expect(stacked.series.every((s) => s.stack === "total")).toBe(true);
    expect(stacked.series[0].data).toEqual([10, 20]);
});

test("marked lines show the maximum, minimum and average", async () => {
    const option = await getOption(DashBoardMarkedLineWidget, WEEK);
    expect(option.series[0].markPoint.data.map((p) => p.type)).toEqual(["max", "min"]);
    expect(option.series[0].markLine.data[0].type).toBe("average");
});

test("the pie totals each category and the lines follow the same data", async () => {
    const option = await getOption(DashBoardPieLineWidget, WEEK);
    const pie = option.series[0];
    expect(pie.type).toBe("pie");
    expect(pie.data).toEqual([
        { name: "A", value: 30 },
        { name: "B", value: 13 },
    ]);
    expect(option.series.slice(1).map((s) => s.type)).toEqual(["line", "line"]);
});

test("radial, tangential and end angle polar bars put the names on the right axis", async () => {
    const radial = await getOption(DashBoardPolarRadialWidget, WEEK);
    expect(radial.radiusAxis.type).toBe("category");
    expect(radial.angleAxis.type).toBe("value");
    expect(radial.series[0].coordinateSystem).toBe("polar");

    const tangential = await getOption(DashBoardPolarTangentialWidget, WEEK);
    expect(tangential.angleAxis.type).toBe("category");
    expect(tangential.radiusAxis.type).toBe("value");

    const rose = await getOption(DashBoardPolarEndAngleWidget, WEEK);
    expect(rose.angleAxis.endAngle).toBe(270);
    const full = await getOption(DashBoardPolarEndAngleWidget, WEEK, { end_angle: 180 });
    expect(full.angleAxis.endAngle).toBe(180);
});

test("a horizontal bar chart has the names on the vertical axis", async () => {
    const option = await getOption(DashBoardHorizontalBarWidget, WEEK);
    expect(option.yAxis.type).toBe("category");
    expect(option.yAxis.data).toEqual(["Mon", "Tue"]);
    expect(option.xAxis.type).toBe("value");
});

test("axis breaks split the axis only when the values differ by more than four times", async () => {
    const broken = await getOption(DashBoardAxisBreakBarWidget, [
        { name: "Mon", value: 100, category: null, filter_domain: [] },
        { name: "Tue", value: 150, category: null, filter_domain: [] },
        { name: "Wed", value: 3000000, category: null, filter_domain: [] },
    ]);
    expect(broken.grid.length).toBe(2);
    expect(broken.yAxis[1].max).toBeGreaterThan(broken.yAxis[1].min);
    expect(broken.yAxis[0].min).toBeGreaterThan(broken.yAxis[1].max);

    const flat = await getOption(DashBoardAxisBreakBarWidget, [
        { name: "Mon", value: 100, category: null, filter_domain: [] },
        { name: "Tue", value: 150, category: null, filter_domain: [] },
    ]);
    expect(flat.grid).toBe(undefined);
    expect(flat.series.length).toBe(1);
});

test("gradient bars have a background shadow and a zoom slider", async () => {
    const option = await getOption(DashBoardGradientBarWidget, WEEK);
    expect(option.series[0].showBackground).toBe(true);
    expect(option.series[0].itemStyle.color.type).toBe("linear");
    expect(option.dataZoom.map((z) => z.type)).toEqual(["inside", "slider"]);
});

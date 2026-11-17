import { describe, expect, test } from "@odoo/hoot";
import { DashBoardRadarWidget } from "@reporting/widget/dashboard_radar/dashboard_radar";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";

describe.current.tags("headless");

const DATA = [
    { name: "Alpha", value: 80, category: "Quality", filter_domain: [] },
    { name: "Alpha", value: 60, category: "Price", filter_domain: [] },
    { name: "Alpha", value: 70, category: "Speed", filter_domain: [] },
    { name: "Beta", value: 50, category: "Quality", filter_domain: [] },
    { name: "Beta", value: 90, category: "Price", filter_domain: [] },
    { name: "Beta", value: 40, category: "Speed", filter_domain: [] },
];

async function getOption(data) {
    const widget = await mountWithCleanup(DashBoardRadarWidget, {
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

test("radar axes are the categories and each name is one polygon", async () => {
    const option = await getOption(DATA);
    expect(option.radar.indicator.map((i) => i.name)).toEqual(["Quality", "Price", "Speed"]);
    expect(option.series[0].data.map((d) => d.name)).toEqual(["Alpha", "Beta"]);
    expect(option.series[0].data[0].value.length).toBe(3);
});

test("a name without a value for a category counts as zero", async () => {
    const option = await getOption([
        { name: "Alpha", value: 10, category: "Quality", filter_domain: [] },
        { name: "Beta", value: 20, category: "Price", filter_domain: [] },
    ]);
    expect(option.series[0].data[0].value).toEqual([10, 0]);
});

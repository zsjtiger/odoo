import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { getFieldWidget } from "@mobile_web/fields/field_widget";
import { DashBoardBarWidget } from "@reporting/widget/dashboard_bar/dashboard_bar";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

const DATA = JSON.stringify([
    { name: "Jan", value: 120, category: null, filter_domain: [["month", "=", "1"]] },
    { name: "Feb", value: 180, category: null, filter_domain: [["month", "=", "2"]] },
]);

test("the reporting widget names resolve to the mobile chart widgets", () => {
    const widget = getFieldWidget({ widget: "board_dashboard_bar" }, { type: "text" });
    expect(widget.prototype instanceof DashBoardBarWidget).toBe(true);
});

test("a bar chart is drawn from the JSON stored in the field", async () => {
    const widget = getFieldWidget({ widget: "board_dashboard_bar" }, { type: "text" });
    await mountWithCleanup(widget, {
        props: fieldProps({
            name: "chart_bar",
            field: { type: "text", string: "Bar" },
            resModel: "reporting.demo",
            readonly: true,
            record: recordOf({ chart_bar: DATA }),
        }),
    });
    await animationFrame();
    expect(queryAll(".snow_mdm_dashboard_chart_container canvas").length).toBe(1);
});

test("clicking a chart opens the list of the records behind the clicked value", async () => {
    const widget = getFieldWidget({ widget: "board_dashboard_bar" }, { type: "text" });
    const instance = await mountWithCleanup(widget, {
        props: fieldProps({
            name: "chart_bar",
            field: { type: "text", string: "Bar" },
            resModel: "reporting.demo",
            readonly: true,
            record: recordOf({ chart_bar: DATA }),
        }),
    });
    const actions = [];
    instance.actionService.doAction = (action) => actions.push(action);
    instance._doPageAction("Feb", null);
    expect(actions.length).toBe(1);
    expect(actions[0].res_model).toBe("reporting.demo");
    expect(actions[0].views).toEqual([[false, "list"]]);
    expect(actions[0].domain).toEqual([["month", "=", "2"]]);
});

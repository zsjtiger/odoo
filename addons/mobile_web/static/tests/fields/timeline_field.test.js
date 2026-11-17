import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { TimelineField } from "@mobile_web/fields/timeline_field";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

class Visit extends models.Model {
    _name = "visit.line";
    name = fields.Char();
    visit_date = fields.Date();
    note = fields.Char();
    _records = [
        { id: 1, name: "Report A", visit_date: "2026-04-26", note: "2 visits" },
        { id: 2, name: "Report B", visit_date: "2026-06-17", note: "1 visit" },
        { id: 3, name: "Report C", visit_date: "2026-06-10", note: "0 meetings" },
    ];
}

defineModels([Visit]);

function mockViews() {
    onRpc("visit.line", "get_views", () => ({
        models: {
            "visit.line": {
                fields: {
                    name: { type: "char", string: "Name" },
                    visit_date: { type: "date", string: "Date" },
                    note: { type: "char", string: "Note" },
                },
            },
        },
        views: {
            list: {
                arch: `<list><field name="visit_date" class="mobile_date"/><field name="name" class="mobile_title"/><field name="note"/></list>`,
                id: 1,
            },
        },
    }));
}

async function settle() {
    for (let i = 0; i < 6; i++) {
        await animationFrame();
    }
}

function mount(readonly = true) {
    return mountWithCleanup(TimelineField, {
        props: fieldProps({
            name: "visit_ids",
            field: { type: "one2many", string: "Visits", relation: "visit.line" },
            readonly,
            record: recordOf({ visit_ids: [[1, "Report A"], [2, "Report B"], [3, "Report C"]] }),
        }),
    });
}

test("the timeline lists the lines newest first, with the title and the other columns", async () => {
    mockViews();
    await mount();
    await settle();
    const titles = queryAll(".m_timeline_item .m_timeline_title").map((el) => el.textContent.trim());
    expect(titles).toEqual(["Report B", "Report C", "Report A"]);
    expect(queryAll(".m_timeline_item .m_timeline_line")[0].textContent).toInclude("1 visit");
});

test("each node shows its date on the left", async () => {
    mockViews();
    await mount();
    await settle();
    expect(queryAll(".m_timeline_item .m_timeline_date").length).toBe(3);
    expect(queryAll(".m_timeline_item .m_timeline_date")[0].textContent.trim()).not.toBe("");
});

test("in edit mode a node opens the line editor and an add button is shown", async () => {
    mockViews();
    await mount(false);
    await settle();
    expect(queryAll(".m_one2many_add").length).toBe(1);
    await click(".m_timeline_item");
    await settle();
    expect(queryAll(".m_line_editor").length).toBe(1);
});

test("in readonly mode there is no add button and clicking a node does nothing", async () => {
    mockViews();
    await mount(true);
    await settle();
    expect(queryAll(".m_one2many_add").length).toBe(0);
    await click(".m_timeline_item");
    await settle();
    expect(queryAll(".m_line_editor").length).toBe(0);
});

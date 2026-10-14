import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { parseArch } from "@mobile_web/views/arch";
import { buildLayout } from "@mobile_web/views/form/layout";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";
import { recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

/** 等待组件完成异步渲染 */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

const FIELDS = {
    name: { type: "char", string: "Name" },
    email: { type: "char", string: "Email" },
    note: { type: "text", string: "Note" },
    street: { type: "char", string: "Street" },
};

function mountBlocks(arch, record = recordOf({ name: "Alpha", email: "a@b.c", note: "", street: "Main" })) {
    const blocks = buildLayout(parseArch(arch), FIELDS);
    return mountWithCleanup(FormBlocks, {
        props: { blocks, record, resModel: "res.partner", onFieldChange: () => {} },
    });
}

test("a group with a string gets a title, and its fields stay together", async () => {
    await mountBlocks(`<form><group string="Contact"><field name="name"/><field name="email"/></group></form>`);
    expect(queryOne(".m_form_group .m_form_separator")).toHaveText("Contact");
    expect(queryAll(".m_form_group .m_form_field").length).toBe(2);
});

test("a group without a string has no title", async () => {
    await mountBlocks(`<form><group><field name="name"/></group></form>`);
    expect(queryAll(".m_form_separator").length).toBe(0);
    expect(queryAll(".m_form_field").length).toBe(1);
});

test("ungrouped fields are shown together, each with its label", async () => {
    await mountBlocks(`<form><field name="name"/><field name="email"/></form>`);
    const labels = queryAll(".m_form_field .m_form_label").map((el) => el.textContent);
    expect(labels).toEqual(["Name", "Email"]);
});

test("long text fields stack their label above the value", async () => {
    await mountBlocks(`<form><field name="note"/></form>`);
    expect(queryOne(".m_form_field")).toHaveClass("is_stacked");
});

test("a separator shows its text as a heading", async () => {
    await mountBlocks(`<form><separator string="Address"/><field name="street"/></form>`);
    expect(queryOne("h3.m_form_separator")).toHaveText("Address");
});

test("notebook pages are shown as tabs, and clicking a tab shows that page", async () => {
    await mountBlocks(`<form>
        <notebook>
            <page string="General"><field name="name"/></page>
            <page string="Address"><field name="street"/></page>
        </notebook>
    </form>`);
    const tabs = queryAll(".m_form_tabs [role=tab]");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["General", "Address"]);
    expect(queryAll(".m_form_field .m_form_label")[0]).toHaveText("Name");
    await click(tabs[1]);
    await settle();
    expect(queryAll(".m_form_field .m_form_label")[0]).toHaveText("Street");
    expect(queryOne(".m_form_tabs .is_active")).toHaveText("Address");
});

test("field values come from the record adapter", async () => {
    await mountBlocks(`<form><field name="name"/></form>`);
    expect(queryOne(".m_form_field input")).toHaveValue("Alpha");
});

test("a statusbar in the header is shown without a label", async () => {
    const root = parseArch(`<form><header><field name="state" widget="statusbar"/></header></form>`);
    const header = root.children.find((child) => child.tag === "header");
    const blocks = buildLayout(header, {
        state: {
            type: "selection",
            string: "State",
            selection: [
                ["draft", "Draft"],
                ["done", "Done"],
            ],
        },
    });
    await mountWithCleanup(FormBlocks, {
        props: { blocks, record: recordOf({ state: "done" }), resModel: "res.partner", onFieldChange: () => {} },
    });
    expect(queryAll(".m_statusbar_item").length).toBe(2);
    expect(queryAll(".m_form_label").length).toBe(0);
});

import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { PriorityField, RadioField, StatusBarField } from "@mobile_web/fields/selection_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

const STATES = [
    ["draft", "Draft"],
    ["done", "Done"],
    ["cancel", "Cancelled"],
];
const PRIORITIES = [
    ["0", "Normal"],
    ["1", "Good"],
    ["2", "Very Good"],
    ["3", "Excellent"],
];

function selectionProps(type, selection, value, overrides = {}) {
    return fieldProps({
        name: "state",
        field: { type: "selection", string: "State", selection },
        record: recordOf({ state: value }),
        ...overrides,
    });
}

test("radio shows every option and marks the current one", async () => {
    await mountWithCleanup(RadioField, { props: selectionProps("selection", STATES, "done") });
    expect(queryAll(".m_radio").length).toBe(3);
    const radios = queryAll("input[type=radio]");
    expect(radios.map((r) => r.checked)).toEqual([false, true, false]);
});

test("radio reports the chosen option's value", async () => {
    const values = [];
    await mountWithCleanup(RadioField, {
        props: selectionProps("selection", STATES, "draft", { onChange: (v) => values.push(v) }),
    });
    const radio = queryAll("input[type=radio]")[2];
    radio.checked = true;
    radio.dispatchEvent(new Event("change"));
    expect(values).toEqual(["cancel"]);
});

test("radio shows the label when readonly", async () => {
    await mountWithCleanup(RadioField, {
        props: selectionProps("selection", STATES, "done", { readonly: true }),
    });
    expect(queryOne(".m_field_value")).toHaveText("Done");
});

test("statusbar shows only the current state", async () => {
    await mountWithCleanup(StatusBarField, { props: selectionProps("selection", STATES, "done") });
    const items = queryAll(".m_statusbar_item");
    expect(items.length).toBe(1);
    expect(items[0].textContent).toBe("Done");
    expect(items[0].classList.contains("is_active")).toBe(true);
});

test("clicking the statusbar changes nothing", async () => {
    const values = [];
    await mountWithCleanup(StatusBarField, {
        props: selectionProps("selection", STATES, "draft", { onChange: (v) => values.push(v) }),
    });
    await click(queryAll(".m_statusbar_item")[0]);
    expect(values).toEqual([]);
    expect(queryAll(".m_statusbar_item")[0].textContent).toBe("Draft");
});

test("the statusbar in readonly mode shows the same state", async () => {
    await mountWithCleanup(StatusBarField, {
        props: selectionProps("selection", STATES, "draft", { readonly: true }),
    });
    expect(queryAll(".m_statusbar_item").length).toBe(1);
    expect(queryAll(".m_statusbar_item")[0].textContent).toBe("Draft");
});

test("priority shows one star per option after the first", async () => {
    await mountWithCleanup(PriorityField, { props: selectionProps("selection", PRIORITIES, "0") });
    expect(queryAll(".m_priority_star").length).toBe(3);
    expect(queryAll(".m_priority_star.is_active").length).toBe(0);
});

test("priority fills the stars up to the current level", async () => {
    await mountWithCleanup(PriorityField, { props: selectionProps("selection", PRIORITIES, "2") });
    expect(queryAll(".m_priority_star").map((el) => el.classList.contains("is_active"))).toEqual([true, true, false]);
});

test("clicking a star sets that priority", async () => {
    const values = [];
    await mountWithCleanup(PriorityField, {
        props: selectionProps("selection", PRIORITIES, "1", { onChange: (v) => values.push(v) }),
    });
    await click(queryAll(".m_priority_star")[2]);
    expect(values).toEqual(["3"]);
});

test("clicking the current top star clears the priority", async () => {
    const values = [];
    await mountWithCleanup(PriorityField, {
        props: selectionProps("selection", PRIORITIES, "2", { onChange: (v) => values.push(v) }),
    });
    await click(queryAll(".m_priority_star")[1]);
    expect(values).toEqual(["0"]);
});

test("priority shows its stars as text when readonly", async () => {
    await mountWithCleanup(PriorityField, {
        props: selectionProps("selection", PRIORITIES, "2", { readonly: true }),
    });
    expect(queryOne(".m_priority_text")).toHaveText("★★☆");
});

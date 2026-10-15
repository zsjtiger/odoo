import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SortFilterBar } from "@mobile_web/widgets/sort_filter/sort_filter";

describe.current.tags("mobile");

const FILTER = [
    { name: "name", label: "Name", type: "char" },
    { name: "active", label: "Active", type: "boolean" },
    { name: "state", label: "State", type: "selection", selection: [["a", "Draft"], ["b", "Done"]] },
];

function select(el, value) {
    el.value = value;
    el.dispatchEvent(new Event("change"));
}

/** Owl 的渲染是异步的: 变化之后等待渲染完成再查询 DOM */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("the bar only offers filters, no sort field", async () => {
    await mountWithCleanup(SortFilterBar, { props: { filterFields: FILTER, onChange: () => {} } });
    expect(queryAll(".m_sort_filter select").length).toBe(1);
    expect(queryAll(".m_sort_filter_dir").length).toBe(0);
});

test("a boolean filter offers yes and no", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, { props: { filterFields: FILTER, onChange: (e) => events.push(e) } });
    select(queryAll("select")[0], "active");
    await settle();
    const options = [...queryAll("select")[1].querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["All", "Yes", "No"]);
    select(queryAll("select")[1], "false");
    await settle();
    expect(events.at(-1)).toEqual({ filter: { name: "active", type: "boolean", value: "false" } });
});

test("a selection filter offers its options", async () => {
    await mountWithCleanup(SortFilterBar, { props: { filterFields: FILTER, onChange: () => {} } });
    select(queryAll("select")[0], "state");
    await settle();
    const options = [...queryAll("select")[1].querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["All", "Draft", "Done"]);
});

test("a text filter uses a text input and reports the trimmed value", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, { props: { filterFields: FILTER, onChange: (e) => events.push(e) } });
    select(queryAll("select")[0], "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "  Alp  ";
    input.dispatchEvent(new Event("change"));
    expect(events.at(-1)).toEqual({ filter: { name: "name", type: "char", value: "Alp" } });
});

test("clearing the filter field reports no filter", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, { props: { filterFields: FILTER, onChange: (e) => events.push(e) } });
    select(queryAll("select")[0], "name");
    await settle();
    select(queryAll("select")[0], "");
    await settle();
    await settle();
    expect(events.at(-1)).toEqual({ filter: null });
});

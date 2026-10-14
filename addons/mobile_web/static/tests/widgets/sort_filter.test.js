import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SortFilterBar } from "@mobile_web/widgets/sort_filter/sort_filter";

describe.current.tags("mobile");

const SORT = [
    { name: "name", label: "Name", type: "char" },
    { name: "amount", label: "Amount", type: "float" },
];
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

test("choosing a sort field reports the ascending order", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, {
        props: { sortFields: SORT, filterFields: FILTER, onChange: (e) => events.push(e) },
    });
    select(queryAll("select")[0], "name");
    await settle();
    expect(events).toEqual([{ order: "name ASC", filter: null }]);
});

test("the direction button toggles between ascending and descending", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, {
        props: { sortFields: SORT, filterFields: FILTER, onChange: (e) => events.push(e) },
    });
    select(queryAll("select")[0], "amount");
    await settle();
    await click(".m_sort_filter_dir");
    await settle();
    expect(events.map((e) => e.order)).toEqual(["amount ASC", "amount DESC"]);
});

test("the direction button only appears once a sort field is chosen", async () => {
    await mountWithCleanup(SortFilterBar, { props: { sortFields: SORT, filterFields: FILTER, onChange: () => {} } });
    expect(queryAll(".m_sort_filter_dir").length).toBe(0);
});

test("a boolean filter offers yes and no", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, {
        props: { sortFields: SORT, filterFields: FILTER, onChange: (e) => events.push(e) },
    });
    select(queryAll("select")[1], "active");
    await settle();
    const options = [...queryAll("select")[2].querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["All", "Yes", "No"]);
    select(queryAll("select")[2], "false");
    await settle();
    expect(events.at(-1).filter).toEqual({ name: "active", type: "boolean", value: "false" });
});

test("a selection filter offers its options", async () => {
    await mountWithCleanup(SortFilterBar, { props: { sortFields: SORT, filterFields: FILTER, onChange: () => {} } });
    select(queryAll("select")[1], "state");
    await settle();
    const options = [...queryAll("select")[2].querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["All", "Draft", "Done"]);
});

test("a text filter uses a text input and reports the trimmed value", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, {
        props: { sortFields: SORT, filterFields: FILTER, onChange: (e) => events.push(e) },
    });
    select(queryAll("select")[1], "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "  Alp  ";
    input.dispatchEvent(new Event("change"));
    expect(events.at(-1).filter).toEqual({ name: "name", type: "char", value: "Alp" });
});

test("clearing the filter field reports no filter", async () => {
    const events = [];
    await mountWithCleanup(SortFilterBar, {
        props: { sortFields: SORT, filterFields: FILTER, onChange: (e) => events.push(e) },
    });
    select(queryAll("select")[1], "name");
    await settle();
    select(queryAll("select")[1], "");
    await settle();
    await settle();
    expect(events.at(-1).filter).toBe(null);
});

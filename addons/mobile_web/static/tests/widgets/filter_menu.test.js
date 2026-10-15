import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { FilterMenu } from "@mobile_web/widgets/filter_menu/filter_menu";

describe.current.tags("mobile");

const FIELDS = [
    { name: "name", label: "Name", type: "char" },
    { name: "amount", label: "Amount", type: "float" },
    { name: "active", label: "Active", type: "boolean" },
    { name: "state", label: "State", type: "selection", selection: [["draft", "Draft"], ["done", "Done"]] },
];

async function settle() {
    for (let i = 0; i < 6; i++) {
        await animationFrame();
    }
}

function select(el, value) {
    el.value = value;
    el.dispatchEvent(new Event("change"));
}

async function mountMenu(onChange = () => {}) {
    await mountWithCleanup(FilterMenu, { props: { filterFields: FIELDS, onChange } });
    return onChange;
}

/** 面板未打开时才打开它: 点击按钮会切换展开状态 */
async function openPanel() {
    if (!queryAll(".m_filter_menu_panel").length) {
        await click(".m_filter_menu_toggle");
        await settle();
    }
}

/** 打开面板, 选择字段并填写值, 点击添加 */
async function addCondition(name, value) {
    await openPanel();
    select(queryAll(".m_filter_add select")[0], name);
    await settle();
    const input = queryOne(".m_filter_input");
    input.value = value;
    input.dispatchEvent(new Event("change"));
    await settle();
    await click(".m_filter_add_btn");
    await settle();
}

function chipTexts() {
    return queryAll(".m_filter_chip_text").map((el) => el.textContent.trim());
}

test("the toggle opens a panel listing every filterable field", async () => {
    await mountMenu();
    await click(".m_filter_menu_toggle");
    await settle();
    const options = [...queryAll(".m_filter_add select")[0].querySelectorAll("option")].map((o) => o.textContent.trim());
    expect(options).toEqual(["Choose a filter", "Name", "Amount", "Active", "State"]);
});

test("a condition added to the list is hidden from the dropdown", async () => {
    await mountMenu();
    await addCondition("name", "Alp");
    expect(chipTexts()).toEqual(["Name: Alp"]);
    const options = [...queryAll(".m_filter_add select")[0].querySelectorAll("option")].map((o) => o.textContent.trim());
    expect(options.includes("Name")).toBe(false);
});

test("the add button stays disabled until a value is entered", async () => {
    await mountMenu();
    await click(".m_filter_menu_toggle");
    await settle();
    select(queryAll(".m_filter_add select")[0], "name");
    await settle();
    expect(queryOne(".m_filter_add_btn")).toHaveAttribute("disabled");
});

test("confirm applies every added condition", async () => {
    const calls = [];
    await mountMenu((e) => calls.push(e));
    await addCondition("name", "Alp");
    await addCondition("amount", "3");
    await click(".m_filter_confirm");
    await settle();
    expect(calls.at(-1)).toEqual({
        filters: [
            { name: "name", type: "char", value: "Alp" },
            { name: "amount", type: "float", value: "3" },
        ],
    });
    expect(queryAll(".m_filter_menu_panel").length).toBe(0);
    expect(queryOne(".m_filter_menu_toggle")).toHaveText("Filter (2) ▼");
});

test("cancel discards the changes that were not confirmed", async () => {
    const calls = [];
    await mountMenu((e) => calls.push(e));
    await addCondition("name", "Alp");
    await click(".m_filter_cancel");
    await settle();
    expect(calls.length).toBe(0);
    await click(".m_filter_menu_toggle");
    await settle();
    expect(queryAll(".m_filter_chip").length).toBe(0);
});

test("reopening shows the confirmed conditions", async () => {
    await mountMenu();
    await addCondition("name", "Alp");
    await click(".m_filter_confirm");
    await settle();
    await click(".m_filter_menu_toggle");
    await settle();
    expect(chipTexts()).toEqual(["Name: Alp"]);
});

test("clear removes every condition at once and reports no filters", async () => {
    const calls = [];
    await mountMenu((e) => calls.push(e));
    await addCondition("name", "Alp");
    await click(".m_filter_confirm");
    await settle();
    await click(".m_filter_menu_toggle");
    await settle();
    await click(".m_filter_clear");
    await settle();
    expect(calls.at(-1)).toEqual({ filters: [] });
    expect(queryAll(".m_filter_menu_panel").length).toBe(0);
});

test("removing a chip drops that condition before confirming", async () => {
    const calls = [];
    await mountMenu((e) => calls.push(e));
    await addCondition("name", "Alp");
    await addCondition("amount", "3");
    await click(queryAll(".m_filter_chip_remove")[0]);
    await settle();
    expect(chipTexts()).toEqual(["Amount: 3"]);
    await click(".m_filter_confirm");
    await settle();
    expect(calls.at(-1)).toEqual({ filters: [{ name: "amount", type: "float", value: "3" }] });
});

test("a boolean condition offers yes and no and shows the chosen text", async () => {
    await mountMenu();
    await click(".m_filter_menu_toggle");
    await settle();
    select(queryAll(".m_filter_add select")[0], "active");
    await settle();
    const options = [...queryAll(".m_filter_add select")[1].querySelectorAll("option")].map((o) => o.textContent.trim());
    expect(options).toEqual(["All", "Yes", "No"]);
    select(queryAll(".m_filter_add select")[1], "false");
    await settle();
    await click(".m_filter_add_btn");
    await settle();
    expect(chipTexts()).toEqual(["Active: No"]);
});

test("a selection condition shows the label of the chosen option", async () => {
    await mountMenu();
    await click(".m_filter_menu_toggle");
    await settle();
    select(queryAll(".m_filter_add select")[0], "state");
    await settle();
    select(queryAll(".m_filter_add select")[1], "done");
    await settle();
    await click(".m_filter_add_btn");
    await settle();
    expect(chipTexts()).toEqual(["State: Done"]);
});

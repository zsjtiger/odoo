import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SortMenu } from "@mobile_web/widgets/sort_menu/sort_menu";

describe.current.tags("mobile");

const SORT = [
    { name: "name", label: "Name", type: "char" },
    { name: "amount", label: "Amount", type: "float" },
];

/** Owl 的渲染是异步的: 点击之后等待渲染完成再查询 DOM */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

function itemTexts() {
    return queryAll(".m_sort_menu_panel [role=option]").map((el) => el.textContent.replace("✓", "").trim());
}

function selectedTexts() {
    return queryAll(".m_sort_menu_panel [aria-selected=true]").map((el) => el.textContent.replace("✓", "").trim());
}

test("the menu is closed until the toggle is pressed", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    expect(queryAll(".m_sort_menu_panel").length).toBe(0);
    await click(".m_sort_menu_toggle");
    await settle();
    expect(queryOne(".m_sort_menu_toggle")).toHaveAttribute("aria-expanded", "true");
    expect(queryAll(".m_sort_menu_panel").length).toBe(1);
});

test("the panel lists the default order and every sortable field", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    await click(".m_sort_menu_toggle");
    await settle();
    expect(itemTexts()).toEqual(["Default order", "Name", "Amount"]);
    expect(selectedTexts()).toEqual(["Default order"]);
});

test("picking a field reports its ascending order and closes the panel", async () => {
    const events = [];
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: (e) => events.push(e) } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click('.m_sort_menu_item[data-name="name"]');
    await settle();
    expect(events).toEqual([{ order: "name ASC" }]);
    expect(queryAll(".m_sort_menu_panel").length).toBe(0);
});

test("the direction radios appear once a field is chosen and report descending", async () => {
    const events = [];
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: (e) => events.push(e) } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click('.m_sort_menu_item[data-name="amount"]');
    await settle();
    await click(".m_sort_menu_toggle");
    await settle();
    expect(itemTexts()).toEqual(["Default order", "Name", "Amount", "Ascending", "Descending"]);
    expect(selectedTexts()).toEqual(["Amount", "Ascending"]);
    await click('.m_sort_menu_item[data-dir="desc"]');
    await settle();
    expect(events.at(-1)).toEqual({ order: "amount DESC" });
});

test("choosing the default order reports an empty order", async () => {
    const events = [];
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: (e) => events.push(e) } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click('.m_sort_menu_item[data-name="name"]');
    await settle();
    await click(".m_sort_menu_toggle");
    await settle();
    await click('.m_sort_menu_item[data-name=""]');
    await settle();
    expect(events.at(-1)).toEqual({ order: "" });
});

test("the toggle is highlighted while a sort is active", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    expect(queryOne(".m_sort_menu_toggle")).not.toHaveClass("is_active");
    await click(".m_sort_menu_toggle");
    await settle();
    await click('.m_sort_menu_item[data-name="name"]');
    await settle();
    expect(queryOne(".m_sort_menu_toggle")).toHaveClass("is_active");
});

test("the icon-only toggle has an accessible label and no text", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {}, iconOnly: true } });
    const toggle = queryAll(".m_sort_menu_toggle")[0];
    expect(toggle.getAttribute("aria-label")).toBe("Sort");
    expect(toggle.querySelectorAll("svg").length).toBe(1);
});

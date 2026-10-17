import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SortMenu } from "@mobile_web/widgets/sort_menu/sort_menu";

describe.current.tags("mobile");

const SORT = [
    { name: "name", label: "Name", type: "char" },
    { name: "amount", label: "Amount", type: "float" },
    { name: "email", label: "Email", type: "char" },
];

/** Owl 的渲染是异步的: 点击之后等待渲染完成再查询 DOM */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

function chip(name) {
    return queryOne(`.m_sort_chip[data-name="${name}"]`);
}

test("the sheet is closed until the sort icon is pressed", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    expect(queryAll(".m_sort_sheet").length).toBe(0);
    await click(".m_sort_menu_toggle");
    await settle();
    expect(queryAll(".m_sort_sheet").length).toBe(1);
});

test("the sheet lists every sortable field as a chip", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    await click(".m_sort_menu_toggle");
    await settle();
    expect(queryAll(".m_sort_chip").map((el) => el.textContent.trim())).toEqual(["Name", "Amount", "Email"]);
});

test("a chip cycles from ascending to descending and then off", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click(chip("name"));
    await settle();
    expect(chip("name").textContent.trim()).toBe("Name ↑");
    expect(chip("name").classList.contains("is_on")).toBe(true);
    await click(chip("name"));
    await settle();
    expect(chip("name").textContent.trim()).toBe("Name ↓");
    await click(chip("name"));
    await settle();
    expect(chip("name").textContent.trim()).toBe("Name");
    expect(chip("name").classList.contains("is_on")).toBe(false);
});

test("confirm reports the selected fields in the order they were picked", async () => {
    const orders = [];
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: ({ order }) => orders.push(order) } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click(chip("name"));
    await click(chip("email"));
    await click(chip("email"));
    await settle();
    await click(".m_sheet_btn_primary");
    await settle();
    expect(orders).toEqual(["name ASC, email DESC"]);
    expect(queryAll(".m_sort_sheet").length).toBe(0);
});

test("cancel leaves the sort unchanged", async () => {
    const orders = [];
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: ({ order }) => orders.push(order) } });
    await click(".m_sort_menu_toggle");
    await settle();
    await click(chip("amount"));
    await settle();
    await click(".m_sheet_btn:not(.m_sheet_btn_primary)");
    await settle();
    expect(orders).toEqual([]);
});

test("the icon has an accessible label and no text", async () => {
    await mountWithCleanup(SortMenu, { props: { sortFields: SORT, onChange: () => {} } });
    const toggle = queryAll(".m_sort_menu_toggle")[0];
    expect(toggle.getAttribute("aria-label")).toBe("Sort");
    expect(toggle.querySelectorAll("svg").length).toBe(1);
});

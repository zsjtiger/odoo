import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models } from "@web/../tests/web_test_helpers";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";
import { MobileKanbanView } from "@mobile_web/views/kanban/mobile_kanban_view";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    email = fields.Char();
    _records = [
        { id: 1, name: "Alpha", email: "a@example.com" },
        { id: 2, name: "Beta", email: false },
        { id: 3, name: "Gamma", email: "g@example.com" },
    ];
}

defineModels([Partner]);

const FIELDS = {
    name: { type: "char", string: "Name" },
    email: { type: "char", string: "Email" },
};

const LIST_ARCH = `<list><field name="name" class="mobile_title"/><field name="email"/></list>`;
const KANBAN_ARCH = `<kanban><templates><t t-name="card"><div><field name="name" class="mobile_title"/></div></t></templates></kanban>`;

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

function rowNames() {
    return queryAll(".m_list_row .m_list_primary").map((el) => el.textContent.trim());
}

function cardNames() {
    return queryAll(".m_kanban_card .m_kanban_title").map((el) => el.textContent.trim());
}

function select(el, value) {
    el.value = value;
    el.dispatchEvent(new Event("change"));
}

/** 在工具条的排序菜单中选择一个字段 */
async function pickSort(name) {
    await click(".m_sort_menu_toggle");
    await settle();
    await click(`.m_sort_menu_item[data-name="${name}"]`);
    await settle();
}

/** 在排序菜单中选择升序或降序 (需要已选择排序字段) */
async function pickDirection(dir) {
    await click(".m_sort_menu_toggle");
    await settle();
    await click(`.m_sort_menu_item[data-dir="${dir}"]`);
    await settle();
}

test("the toolbar shows the sort menu and the filter bar shows only the filter", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    expect(queryAll(".m_list_meta .m_sort_menu_toggle").length).toBe(1);
    expect(queryAll(".m_sort_filter select").length).toBe(1);
    expect(queryAll(".m_sort_filter_dir").length).toBe(0);
});

test("sorting the list by name reorders the rows, and the direction radio reverses them", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await pickSort("name");
    expect(rowNames()).toEqual(["Alpha", "Beta", "Gamma"]);
    await pickDirection("desc");
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("filtering the list by name keeps only the matching rows", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    select(queryOne(".m_sort_filter select"), "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "amm";
    input.dispatchEvent(new Event("change"));
    await settle();
    await settle();
    expect(rowNames()).toEqual(["Gamma"]);
});

test("the sort and the filter work together and the sort survives a filter change", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await pickSort("name");
    await pickDirection("desc");
    select(queryOne(".m_sort_filter select"), "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "a";
    input.dispatchEvent(new Event("change"));
    await settle();
    await settle();
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("the kanban sorts its cards with the same menu", async () => {
    await mountWithCleanup(MobileKanbanView, {
        props: { resModel: "res.partner", arch: KANBAN_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await pickSort("name");
    await pickDirection("desc");
    expect(cardNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

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

/** 在筛选菜单中添加一个条件 (字段 + 值), 然后确定 */
async function filterBy(fieldName, value) {
    await click(".m_filter_menu_toggle");
    await settle();
    const fieldSelect = queryAll(".m_filter_add select")[0];
    fieldSelect.value = fieldName;
    fieldSelect.dispatchEvent(new Event("change"));
    await settle();
    const input = queryOne(".m_filter_input");
    input.value = value;
    input.dispatchEvent(new Event("change"));
    await settle();
    await click(".m_filter_add_btn");
    await settle();
    await click(".m_filter_confirm");
    await settle();
}

test("the toolbar shows the sort and filter menus", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    expect(queryAll(".m_list_meta .m_sort_menu_toggle").length).toBe(1);
    expect(queryAll(".m_list_meta .m_filter_menu_toggle").length).toBe(1);
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

test("a confirmed filter keeps only the matching rows", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await filterBy("name", "amm");
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
    await filterBy("name", "a");
    await settle();
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("clearing the filters shows every row again", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await filterBy("name", "amm");
    await settle();
    expect(rowNames()).toEqual(["Gamma"]);
    await click(".m_filter_menu_toggle");
    await settle();
    await click(".m_filter_clear");
    await settle();
    await settle();
    expect(rowNames()).toEqual(["Alpha", "Beta", "Gamma"]);
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

test("the sort menu lists only the columns marked sortable in the arch", async () => {
    const arch = `<list><field name="name" class="mobile_title" sortable="1"/><field name="email"/></list>`;
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await click(".m_sort_menu_toggle");
    await settle();
    const items = queryAll(".m_sort_menu_panel [role=option]").map((el) => el.textContent.replace("✓", "").trim());
    expect(items).toEqual(["Default order", "Name"]);
});

test("the filter menu lists only the columns marked filterable in the arch", async () => {
    const arch = `<list><field name="name" class="mobile_title" filterable="1"/><field name="email"/></list>`;
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    await click(".m_filter_menu_toggle");
    await settle();
    const options = [...queryAll(".m_filter_add select")[0].querySelectorAll("option")].map((o) => o.textContent.trim());
    expect(options).toEqual(["Choose a filter", "Name"]);
});

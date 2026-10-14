import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne, click } from "@odoo/hoot-dom";
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

test("the list shows the sort bar when its fields can be sorted or filtered", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    expect(queryAll(".m_sort_filter select").length).toBe(2);
});

test("sorting the list by name reorders the rows, and the direction button reverses them", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    select(queryAll(".m_sort_filter select")[0], "name");
    await settle();
    await settle();
    expect(rowNames()).toEqual(["Alpha", "Beta", "Gamma"]);
    await click(".m_sort_filter_dir");
    await settle();
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("filtering the list by name keeps only the matching rows", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    select(queryAll(".m_sort_filter select")[1], "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "amm";
    input.dispatchEvent(new Event("change"));
    await settle();
    await settle();
    expect(rowNames()).toEqual(["Gamma"]);
});

test("the sort and the filter work together", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    select(queryAll(".m_sort_filter select")[1], "name");
    await settle();
    const input = queryOne(".m_sort_filter_input");
    input.value = "a";
    input.dispatchEvent(new Event("change"));
    await settle();
    select(queryAll(".m_sort_filter select")[0], "name");
    await settle();
    await click(".m_sort_filter_dir");
    await settle();
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("the kanban sorts its cards with the same bar", async () => {
    await mountWithCleanup(MobileKanbanView, {
        props: { resModel: "res.partner", arch: KANBAN_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    select(queryAll(".m_sort_filter select")[0], "name");
    await settle();
    await click(".m_sort_filter_dir");
    await settle();
    expect(cardNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

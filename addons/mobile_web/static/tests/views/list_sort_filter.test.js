import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
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

test("the list shows its rows in the order it is given by the search bar", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], order: "name DESC", context: {}, onSelect: () => {} },
    });
    await settle();
    expect(rowNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

test("the default order keeps the server order", async () => {
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], order: "", context: {}, onSelect: () => {} },
    });
    await settle();
    expect(rowNames()).toEqual(["Alpha", "Beta", "Gamma"]);
});

test("the kanban shows its cards in the order it is given by the search bar", async () => {
    await mountWithCleanup(MobileKanbanView, {
        props: { resModel: "res.partner", arch: KANBAN_ARCH, fields: FIELDS, domain: [], order: "name DESC", context: {}, onSelect: () => {} },
    });
    await settle();
    expect(cardNames()).toEqual(["Gamma", "Beta", "Alpha"]);
});

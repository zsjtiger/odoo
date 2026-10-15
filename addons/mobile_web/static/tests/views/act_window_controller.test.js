import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { router } from "@mobile_web/core/browser/router";
import { MobileActWindowController } from "@mobile_web/views/act_window/act_window_controller";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    email = fields.Char();
    _records = [
        { id: 1, name: "Alpha", email: "alpha@example.com" },
        { id: 2, name: "Beta", email: false },
    ];
}

defineModels([Partner]);

const FIELDS = {
    name: { type: "char", string: "Name" },
    email: { type: "char", string: "Email" },
    display_name: { type: "char", string: "Display name" },
};

const LIST_ARCH = `<list><field name="name" class="mobile_title"/><field name="email"/></list>`;
const FORM_ARCH = `<form><sheet><group><field name="name"/><field name="email"/></group></sheet></form>`;

/** 按 action 中声明的视图, 返回 get_views 的结果 (与服务端格式一致) */
function mockViews() {
    onRpc("res.partner", "get_views", () => ({
        models: { "res.partner": { fields: FIELDS } },
        views: {
            list: { arch: LIST_ARCH, id: 1 },
            form: { arch: FORM_ARCH, id: 2 },
        },
    }));
}

function action(overrides = {}) {
    return {
        id: 11,
        type: "ir.actions.act_window",
        display_name: "Partners",
        res_model: "res.partner",
        views: [
            [1, "list"],
            [2, "form"],
        ],
        context: false,
        domain: false,
        ...overrides,
    };
}

/** 等待视图加载与渲染 */
async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

test("the default view is the list, with one row per record", async () => {
    mockViews();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    expect(queryAll(".m_list_row").length).toBe(2);
});

test("a record id opens the form for that record", async () => {
    mockViews();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action(), resId: 1 } });
    await settle();
    expect(queryAll(".m_form_view").length).toBe(1);
    expect(queryAll(".m_form_field input")[0]).toHaveValue("Alpha");
});

/** 记录每次列表查询的 domain */
function recordDomains() {
    const domains = [];
    onRpc("res.partner", "web_search_read", ({ kwargs }) => {
        domains.push(kwargs.domain);
    });
    return domains;
}

function typeText(text) {
    const input = queryOne(".m_search_input");
    input.value = text;
    input.dispatchEvent(new Event("input"));
    return input;
}

test("typing shows one suggestion per searchable field", async () => {
    mockViews();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    typeText("Alp");
    await settle();
    expect(queryAll(".m_search_row").map((el) => el.textContent.trim())).toEqual([
        "Search Name for: Alp",
        "Search Email for: Alp",
    ]);
});

test("choosing a suggestion adds a facet and filters the list by that field", async () => {
    mockViews();
    const domains = recordDomains();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    typeText("Alp");
    await settle();
    await click(".m_search_row");
    await settle();
    expect(queryAll(".m_facet_text").map((el) => el.textContent.trim())).toEqual(["Name: Alp"]);
    expect(domains.at(-1)).toEqual([["name", "ilike", "Alp"]]);
    expect(queryAll(".m_list_row").length).toBe(1);
    expect(queryOne(".m_search_input")).toHaveValue("");
});

test("pressing enter adds the first suggestion", async () => {
    mockViews();
    const domains = recordDomains();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    const input = typeText("Beta");
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await settle();
    expect(domains.at(-1)).toEqual([["name", "ilike", "Beta"]]);
});

test("removing a facet restores the rows", async () => {
    mockViews();
    const domains = recordDomains();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    typeText("Alp");
    await settle();
    await click(".m_search_row");
    await settle();
    await click(".m_facet_remove");
    await settle();
    expect(queryAll(".m_facet").length).toBe(0);
    expect(domains.at(-1)).toEqual([]);
    expect(queryAll(".m_list_row").length).toBe(2);
});

test("the clear button appears beside the search once there are conditions and removes them all", async () => {
    mockViews();
    const domains = recordDomains();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    expect(queryAll(".m_search_clear").length).toBe(0);
    typeText("Alp");
    await settle();
    await click(".m_search_row");
    await settle();
    expect(queryAll(".m_search_clear").length).toBe(1);
    await click(".m_search_clear");
    await settle();
    expect(queryAll(".m_facet").length).toBe(0);
    expect(queryAll(".m_search_clear").length).toBe(0);
    expect(domains.at(-1)).toEqual([]);
    expect(queryAll(".m_list_row").length).toBe(2);
});

test("the create button opens an empty form", async () => {
    mockViews();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    await click(".m_create_btn");
    await settle();
    expect(queryAll(".m_form_field input")[0]).toHaveValue("");
});

test("an action without a form view has no create button", async () => {
    mockViews();
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, {
        props: { action: action({ views: [[1, "list"]] }) },
    });
    await settle();
    expect(queryAll(".m_create_btn").length).toBe(0);
});

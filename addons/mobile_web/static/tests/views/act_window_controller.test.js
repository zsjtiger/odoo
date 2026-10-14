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

test("searching by enter filters the list through the server-side domain", async () => {
    mockViews();
    let searchText = null;
    onRpc("/mobile_web/search_domain", async (req) => {
        searchText = (await req.json()).params.text;
        return [["name", "ilike", "Alpha"]];
    });
    patchWithCleanup(router, { pushState() {} });
    await mountWithCleanup(MobileActWindowController, { props: { action: action() } });
    await settle();
    const input = queryOne(".m_search_input");
    input.value = "Alpha";
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await settle();
    expect(searchText).toBe("Alpha");
    expect(queryAll(".m_list_row").length).toBe(1);
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

import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";
import { MobileKanbanView } from "@mobile_web/views/kanban/mobile_kanban_view";
import { MobileFormView } from "@mobile_web/views/form/mobile_form_view";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    email = fields.Char();
    active = fields.Boolean({ default: true });
    parent_id = fields.Many2one({ relation: "res.partner" });
    _records = [
        { id: 1, name: "Alpha", email: "alpha@example.com", active: true, parent_id: false },
        { id: 2, name: "Beta", email: false, active: false, parent_id: false },
    ];
}

defineModels([Partner]);

/** 移动端视图使用的字段定义(与 loadViews 返回的结构一致) */
const FIELDS = {
    name: { type: "char", string: "Name" },
    email: { type: "char", string: "Email" },
    active: { type: "boolean", string: "Active" },
    parent_id: { type: "many2one", string: "Parent", relation: "res.partner" },
    display_name: { type: "char", string: "Display name" },
};

const LIST_ARCH = `<list>
    <field name="name" class="mobile_title"/>
    <field name="email"/>
    <field name="active"/>
</list>`;

const KANBAN_ARCH = `<kanban>
    <templates>
        <t t-name="card">
            <div><field name="name" class="mobile_title"/></div>
            <div><field name="email"/></div>
        </t>
    </templates>
</kanban>`;

const FORM_ARCH = `<form>
    <sheet>
        <group>
            <field name="name"/>
            <field name="email"/>
            <field name="active"/>
        </group>
    </sheet>
</form>`;

/** 等待组件完成异步更新(onchange / RPC 之后的渲染) */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

/** 在输入框中输入文本并触发 change, 与用户离开输入框时的行为一致 */
function typeValue(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("change"));
}

function listProps(overrides = {}) {
    return {
        resModel: "res.partner",
        arch: LIST_ARCH,
        fields: FIELDS,
        domain: [],
        // 不过滤归档记录, 让测试数据中的 Beta(active=false) 也显示
        context: { active_test: false },
        onSelect: () => {},
        ...overrides,
    };
}

test("list loads the records and shows one row per record", async () => {
    await mountWithCleanup(MobileListView, { props: listProps() });
    expect(queryAll(".m_list_row").length).toBe(2);
});

test("list shows the marked field as the bold title", async () => {
    await mountWithCleanup(MobileListView, { props: listProps() });
    expect(queryAll(".m_list_primary")[0]).toHaveText("Alpha");
});

test("list shows the other fields as values only, without labels", async () => {
    await mountWithCleanup(MobileListView, { props: listProps() });
    const text = queryAll(".m_list_row")[0].textContent;
    expect(text).toInclude("alpha@example.com");
    expect(text).not.toInclude("Email");
});

test("list hides empty values instead of showing placeholders", async () => {
    await mountWithCleanup(MobileListView, { props: listProps() });
    // Beta 没有 email, 只剩 active 为 false 的值(否), 没有孤立的分隔符
    const cells = queryAll(".m_list_row")[1].querySelectorAll(".m_list_cell");
    expect(cells.length).toBe(0);
});

test("clicking a row selects the record", async () => {
    const selected = [];
    await mountWithCleanup(MobileListView, {
        props: listProps({ onSelect: (id) => selected.push(id) }),
    });
    await click(queryAll(".m_list_row")[1]);
    expect(selected).toEqual([2]);
});

test("kanban shows one card per record with the marked title", async () => {
    await mountWithCleanup(MobileKanbanView, {
        props: listProps({ arch: KANBAN_ARCH }),
    });
    expect(queryAll(".m_kanban_card").length).toBe(2);
    expect(queryAll(".m_kanban_title")[0]).toHaveText("Alpha");
});

test("kanban card click selects the record", async () => {
    const selected = [];
    await mountWithCleanup(MobileKanbanView, {
        props: listProps({ arch: KANBAN_ARCH, onSelect: (id) => selected.push(id) }),
    });
    await click(queryAll(".m_kanban_card")[0]);
    expect(selected).toEqual([1]);
});

function formProps(overrides = {}) {
    return {
        resModel: "res.partner",
        arch: FORM_ARCH,
        fields: FIELDS,
        resId: 1,
        context: { active_test: false },
        onSaved: () => {},
        onDiscard: () => {},
        ...overrides,
    };
}

test("form loads the record into the inputs", async () => {
    await mountWithCleanup(MobileFormView, { props: formProps() });
    expect(queryOne(".m_form_title")).toHaveText("Alpha");
    expect(queryAll(".m_form_field input")[0]).toHaveValue("Alpha");
});

test("form shows no unsaved status until a field is changed", async () => {
    await mountWithCleanup(MobileFormView, { props: formProps() });
    expect(queryAll(".m_form_status").length).toBe(0);
    expect(queryOne(".m_form_footer .m_btn_primary")).not.toBeEnabled();
});

test("editing a field marks the form dirty and save writes the change", async () => {
    const writes = [];
    onRpc("res.partner", "web_save", ({ args }) => {
        writes.push(args[1]);
    });
    await mountWithCleanup(MobileFormView, { props: formProps() });
    typeValue(queryAll(".m_form_field input")[0], "Gamma");
    await settle();
    expect(queryOne(".m_form_status")).toHaveText("Unsaved changes");
    await click(".m_form_footer .m_btn_primary");
    await settle();
    expect(writes).toEqual([{ name: "Gamma" }]);
});

test("a new record fills defaults and reports the saved id", async () => {
    const saved = [];
    await mountWithCleanup(MobileFormView, {
        props: formProps({ resId: false, onSaved: (id) => saved.push(id) }),
    });
    expect(queryAll(".m_form_title").length).toBe(0);
    typeValue(queryAll(".m_form_field input")[0], "Delta");
    await settle();
    await click(".m_form_footer .m_btn_primary");
    await settle();
    expect(saved.length).toBe(1);
});

test("discard on a new record calls onDiscard", async () => {
    let discarded = false;
    await mountWithCleanup(MobileFormView, {
        props: formProps({ resId: false, onDiscard: () => (discarded = true) }),
    });
    await click(".m_form_footer .m_btn_secondary");
    expect(discarded).toBe(true);
});

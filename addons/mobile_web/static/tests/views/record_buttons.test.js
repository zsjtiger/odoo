import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { MobileFormView } from "@mobile_web/views/form/mobile_form_view";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";
import { resetMobileActionCalls } from "@mobile_web/../tests/helpers/mobile_action_stub";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    _records = [{ id: 1, name: "Alpha" }];
}

defineModels([Partner]);

const FIELDS = {
    name: { type: "char", string: "Name" },
    display_name: { type: "char", string: "Display name" },
};

const FORM_ARCH = `<form>
    <header>
        <button type="object" name="action_confirm" string="Confirm"/>
        <button type="object" name="action_hidden" string="Hidden" invisible="1"/>
    </header>
    <sheet><group><field name="name"/></group></sheet>
</form>`;

const LIST_ARCH = `<list>
    <button type="object" name="action_confirm" string="Confirm"/>
    <field name="name" class="mobile_title"/>
</list>`;

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

/** 记录所有对 action_confirm 的调用 */
function mockConfirm() {
    const calls = [];
    onRpc("res.partner", "action_confirm", ({ args }) => {
        calls.push(args);
        return false;
    });
    return calls;
}

test("the form shows only visible header buttons, for a saved record", async () => {
    mockConfirm();
    await mountWithCleanup(MobileFormView, {
        props: {
            resModel: "res.partner",
            arch: FORM_ARCH,
            fields: FIELDS,
            resId: 1,
            context: {},
            onSaved: () => {},
            onDiscard: () => {},
        },
    });
    await settle();
    expect(queryAll(".m_form_header_buttons button").map((el) => el.textContent)).toEqual(["Confirm"]);
});

test("clicking a header button runs the method on the record and reloads it", async () => {
    const calls = mockConfirm();
    await mountWithCleanup(MobileFormView, {
        props: {
            resModel: "res.partner",
            arch: FORM_ARCH,
            fields: FIELDS,
            resId: 1,
            context: {},
            onSaved: () => {},
            onDiscard: () => {},
        },
    });
    await settle();
    await click(".m_form_header_buttons button");
    await settle();
    expect(calls).toEqual([[[1]]]);
});

test("a new record has no header buttons", async () => {
    await mountWithCleanup(MobileFormView, {
        props: {
            resModel: "res.partner",
            arch: FORM_ARCH,
            fields: FIELDS,
            resId: false,
            context: {},
            onSaved: () => {},
            onDiscard: () => {},
        },
    });
    await settle();
    expect(queryAll(".m_form_header_buttons").length).toBe(0);
});

test("a list row with actions gets a more button that opens the action sheet", async () => {
    resetMobileActionCalls();
    const calls = mockConfirm();
    await mountWithCleanup(MobileListView, {
        props: {
            resModel: "res.partner",
            arch: LIST_ARCH,
            fields: FIELDS,
            domain: [],
            context: {},
            onSelect: () => {},
        },
    });
    await settle();
    expect(queryAll(".m_row_more").length).toBe(1);
    await click(".m_row_more");
    await settle();
    expect(queryOne(".m_sheet")).not.toBe(null);
    await click(".m_sheet_item");
    await settle();
    expect(calls).toEqual([[[1]]]);
});

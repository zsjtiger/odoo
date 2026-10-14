import { describe, expect, test } from "@odoo/hoot";
import { parseArch } from "@mobile_web/views/arch";
import {
    buttonItems,
    buttonLabel,
    collectButtons,
    isButtonVisible,
    runRecordButton,
} from "@mobile_web/actions/record_buttons";

describe.current.tags("mobile");

const ARCH = parseArch(`<form>
    <header>
        <button type="object" name="action_confirm" string="Confirm"/>
        <button type="action" name="base.action_partner_form" string="Open form"/>
    </header>
    <sheet>
        <group>
            <field name="name">
                <button type="object" name="inside_field" string="Ignored"/>
            </field>
        </group>
    </sheet>
</form>`);

test("collectButtons finds header buttons and ignores buttons inside fields", () => {
    const buttons = collectButtons(ARCH);
    expect(buttons.map((b) => b.attrs.name)).toEqual(["action_confirm", "base.action_partner_form"]);
});

test("collectButtons keeps one button per type and name", () => {
    const root = parseArch(`<list>
        <button type="object" name="dup"/>
        <button type="object" name="dup"/>
    </list>`);
    expect(collectButtons(root).length).toBe(1);
});

test("buttonLabel prefers the string attribute over the name", () => {
    const [confirm] = collectButtons(ARCH);
    expect(buttonLabel(confirm)).toBe("Confirm");
    expect(buttonLabel(parseArch(`<form><button name="go"/></form>`).children[0])).toBe("go");
});

test("a button without invisible is shown", () => {
    const [confirm] = collectButtons(ARCH);
    expect(isButtonVisible(confirm, { state: "draft" })).toBe(true);
});

test("invisible literals hide the button", () => {
    const node = parseArch(`<form><button name="a" invisible="1"/></form>`).children[0];
    expect(isButtonVisible(node, {})).toBe(false);
});

test("invisible expressions are evaluated against the record", () => {
    const node = parseArch(`<form><button name="a" invisible="state == 'done'"/></form>`).children[0];
    expect(isButtonVisible(node, { state: "draft" })).toBe(true);
    expect(isButtonVisible(node, { state: "done" })).toBe(false);
});

test("an expression that cannot be evaluated hides the button", () => {
    const node = parseArch(`<form><button name="a" invisible="unknown_name.x"/></form>`).children[0];
    expect(isButtonVisible(node, {})).toBe(false);
});

test("buttonItems keeps only visible buttons, each with a runner", () => {
    const nodes = parseArch(`<form>
        <button name="a" string="A"/>
        <button name="b" string="B" invisible="1"/>
    </form>`).children;
    const items = buttonItems(nodes, {}, (node) => () => node.attrs.name);
    expect(items.map((i) => i.label)).toEqual(["A"]);
    expect(items[0].run()).toBe("a");
});

test("an object button calls the model method on the record and asks for a reload", async () => {
    const calls = [];
    const orm = {
        call: async (...args) => {
            calls.push(args);
            return true;
        },
    };
    const reload = await runRecordButton({
        node: collectButtons(ARCH)[0],
        resModel: "res.partner",
        resIds: [7],
        context: { lang: "en_US" },
        orm,
        mobileAction: { doAction: async () => {} },
        confirm: () => true,
    });
    expect(reload).toBe(true);
    expect(calls).toEqual([["res.partner", "action_confirm", [[7]], { context: { lang: "en_US" } }]]);
});

test("an object method that returns an action opens it", async () => {
    const opened = [];
    await runRecordButton({
        node: collectButtons(ARCH)[0],
        resModel: "res.partner",
        resIds: [7],
        orm: { call: async () => ({ type: "ir.actions.act_window", id: 3 }) },
        mobileAction: { doAction: async (action) => opened.push(action) },
        confirm: () => true,
    });
    expect(opened).toEqual([{ type: "ir.actions.act_window", id: 3 }]);
});

test("an action button opens the action with the record as context and does not reload", async () => {
    const opened = [];
    const reload = await runRecordButton({
        node: collectButtons(ARCH)[1],
        resModel: "res.partner",
        resIds: [7],
        orm: { call: async () => {
            throw new Error("should not be called");
        } },
        mobileAction: { doAction: async (xmlid, options) => opened.push([xmlid, options]) },
        confirm: () => true,
    });
    expect(reload).toBe(false);
    expect(opened).toEqual([
        ["base.action_partner_form", { additionalContext: { active_id: 7, active_ids: [7], active_model: "res.partner" } }],
    ]);
});

test("declining the confirmation runs nothing", async () => {
    let called = false;
    const reload = await runRecordButton({
        node: parseArch(`<form><button type="object" name="delete_it" confirm="Sure?"/></form>`).children[0],
        resModel: "res.partner",
        resIds: [7],
        orm: { call: async () => (called = true) },
        mobileAction: { doAction: async () => {} },
        confirm: () => false,
    });
    expect(reload).toBe(false);
    expect(called).toBe(false);
});

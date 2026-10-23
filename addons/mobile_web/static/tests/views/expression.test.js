import { describe, expect, test } from "@odoo/hoot";
import { evaluateModifier } from "@mobile_web/views/expression";
import { missingRequiredNames } from "@mobile_web/views/form/modifiers";

describe.current.tags("mobile");

test("static modifiers keep their meaning", () => {
    expect(evaluateModifier("1", {})).toBe(true);
    expect(evaluateModifier("True", {})).toBe(true);
    expect(evaluateModifier("0", {})).toBe(false);
    expect(evaluateModifier(undefined, {}, true)).toBe(true);
});

test("comparisons on field values", () => {
    expect(evaluateModifier("state == 'done'", { state: "done" })).toBe(true);
    expect(evaluateModifier("state == 'done'", { state: "draft" })).toBe(false);
    expect(evaluateModifier("state != 'done'", { state: "draft" })).toBe(true);
    expect(evaluateModifier("amount > 10", { amount: 11 })).toBe(true);
});

test("truthiness of a field, with and without not", () => {
    expect(evaluateModifier("is_urgent", { is_urgent: true })).toBe(true);
    expect(evaluateModifier("not is_urgent", { is_urgent: true })).toBe(false);
    expect(evaluateModifier("not is_urgent", {})).toBe(true);
});

test("many2one values compare by id", () => {
    expect(evaluateModifier("partner_id == 7", { partner_id: [7, "Partner"] })).toBe(true);
    expect(evaluateModifier("partner_id", { partner_id: false })).toBe(false);
});

test("and, or and parentheses", () => {
    const values = { state: "draft", is_urgent: true };
    expect(evaluateModifier("state == 'draft' and is_urgent", values)).toBe(true);
    expect(evaluateModifier("state == 'done' or is_urgent", values)).toBe(true);
    expect(evaluateModifier("(state == 'done' or state == 'cancel') and is_urgent", values)).toBe(false);
});

test("in and not in on lists of values", () => {
    expect(evaluateModifier("state in ('draft', 'confirmed')", { state: "confirmed" })).toBe(true);
    expect(evaluateModifier("state not in ('draft', 'confirmed')", { state: "done" })).toBe(true);
    expect(evaluateModifier("state in ['draft']", { state: "draft" })).toBe(true);
    expect(evaluateModifier("state in ('draft')", { state: "draft" })).toBe(true);
});

test("an expression that cannot be parsed falls back instead of breaking the form", () => {
    expect(evaluateModifier("state ==", {}, true)).toBe(true);
    expect(evaluateModifier("__import__('os')", {}, false)).toBe(false);
});

test("missing required fields are found only where they are visible", () => {
    const field = (name, attrs = {}, required = false) => ({
        kind: "field",
        name,
        attrs,
        field: { required },
        readonly: false,
    });
    const blocks = [
        field("name", { required: "1" }),
        field("note", { required: "is_urgent" }),
        field("reason", { required: "is_urgent", invisible: "not is_urgent" }),
        { kind: "group", children: [field("code", {}, true)] },
        { kind: "notebook", pages: [{ blocks: [field("email", { required: "1" })] }] },
    ];
    expect(missingRequiredNames(blocks, { name: false, is_urgent: true, code: false })).toEqual(["name", "note", "reason", "code", "email"]);
    expect(missingRequiredNames(blocks, { name: "A", is_urgent: false, code: "X", email: "a@b" })).toEqual([]);
});

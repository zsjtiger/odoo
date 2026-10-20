import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    fieldInput,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import {
    castValue,
    fieldKind,
    newGroup,
    parseCustomLogic,
    toDomain,
} from "@advanced_ui/expression_builder/expression_logic";

describe.current.tags("desktop");

const condition = (resource, operator, value, type = "char") => ({
    kind: "condition",
    resource,
    type,
    operator,
    value,
});

const group = (mode, children, customLogic = "") => ({
    kind: "group",
    mode,
    customLogic,
    formula: "",
    children,
});

test("all conditions are joined with AND", () => {
    const tree = group("all", [
        condition("name", "ilike", "Kick"),
        condition("state", "=", "done"),
    ]);
    expect(toDomain(tree)).toEqual([
        "&",
        ["name", "ilike", "Kick"],
        ["state", "=", "done"],
    ]);
});

test("any condition is joined with OR, with a prefix operator per join", () => {
    const tree = group("any", [
        condition("name", "=", "a"),
        condition("name", "=", "b"),
        condition("name", "=", "c"),
    ]);
    expect(toDomain(tree)).toEqual([
        "|",
        "|",
        ["name", "=", "a"],
        ["name", "=", "b"],
        ["name", "=", "c"],
    ]);
});

test("nested groups keep their own mode", () => {
    const tree = group("all", [
        condition("name", "=", "a"),
        group("any", [condition("name", "=", "b"), condition("name", "=", "c")]),
    ]);
    expect(toDomain(tree)).toEqual([
        "&",
        ["name", "=", "a"],
        "|",
        ["name", "=", "b"],
        ["name", "=", "c"],
    ]);
});

test("custom logic combines the numbered conditions, AND binding tighter than OR", () => {
    const children = [
        condition("name", "=", "a"),
        condition("name", "=", "b"),
        condition("name", "=", "c"),
    ];
    expect(toDomain(group("custom", children, "1 AND (2 OR 3)"))).toEqual([
        "&",
        ["name", "=", "a"],
        "|",
        ["name", "=", "b"],
        ["name", "=", "c"],
    ]);
    expect(toDomain(group("custom", children, "NOT 1 OR 2 AND 3"))).toEqual([
        "|",
        "!",
        ["name", "=", "a"],
        "&",
        ["name", "=", "b"],
        ["name", "=", "c"],
    ]);
});

test("custom logic refers to conditions that exist only", () => {
    const children = [condition("name", "=", "a")];
    expect(() => parseCustomLogic("1 AND 2", 1)).toThrow();
    expect(() => parseCustomLogic("1 AND", 1)).toThrow();
    expect(() => parseCustomLogic("(1", 1)).toThrow();
    expect(() => parseCustomLogic("1 + 1", 1)).toThrow();
    expect(toDomain(group("custom", children, "1"))).toEqual([["name", "=", "a"]]);
});

test("set and not set compare the field with false", () => {
    expect(toDomain(group("all", [condition("name", "set", "")]))).toEqual([
        ["name", "!=", false],
    ]);
    expect(toDomain(group("all", [condition("name", "not set", "")]))).toEqual([
        ["name", "=", false],
    ]);
});

test("numbers and booleans are cast to their type", () => {
    expect(castValue("5", "number")).toBe(5);
    expect(castValue("true", "boolean")).toBe(true);
    expect(castValue("false", "boolean")).toBe(false);
    expect(toDomain(group("all", [condition("amount", ">", "5", "number")]))).toEqual([
        ["amount", ">", 5],
    ]);
});

test("incomplete conditions are skipped, and always has no criteria", () => {
    const tree = group("all", [condition("", "", ""), condition("name", "=", "a")]);
    expect(toDomain(tree)).toEqual([["name", "=", "a"]]);
    expect(toDomain(group("always", []))).toEqual([]);
    expect(toDomain(newGroup("all"))).toEqual([]);
});

test("formula mode has no domain", () => {
    expect(toDomain(group("formula", []))).toBe(null);
});

test("field kinds map Odoo field types", () => {
    expect(fieldKind("char")).toBe("char");
    expect(fieldKind("integer")).toBe("number");
    expect(fieldKind("monetary")).toBe("number");
    expect(fieldKind("date")).toBe("date");
    expect(fieldKind("boolean")).toBe("boolean");
    expect(fieldKind("selection")).toBe("selection");
    expect(fieldKind("many2one")).toBe(null);
});

class Event extends models.Model {
    name = fields.Char();
    amount = fields.Integer();
    expr = fields.Char();

    _records = [
        {
            id: 1,
            name: "Kick-off",
            amount: 3,
            expr: JSON.stringify(group("all", [condition("name", "ilike", "Kick")])),
        },
    ];
    _views = {
        form: /* xml */ `
            <form>
                <field name="name"/>
                <field name="expr" widget="expression_builder"/>
            </form>`,
    };
}

defineModels([...webModels, Event]);

test("form: the stored conditions are shown", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    expect(".o_expression_condition").toHaveCount(1);
    expect(".o_expression_resource").toHaveValue("name");
    expect(".o_expression_operator").toHaveValue("ilike");
    expect(".o_expression_value input").toHaveValue("Kick");
});

test("form: a new condition is saved in the expression", async () => {
    onRpc("web_save", ({ args }) => {
        const tree = JSON.parse(args[1].expr);
        expect.step(toDomain(tree));
    });
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await click(".o_expression_add_condition");
    await animationFrame();
    expect(".o_expression_condition").toHaveCount(2);
    await contains(".o_expression_child:last-child .o_expression_resource").select("amount");
    await animationFrame();
    await contains(".o_expression_child:last-child .o_expression_operator").select(">");
    await contains(".o_expression_child:last-child .o_expression_value input").edit("2");
    await contains(".o_form_button_save").click();
    expect.verifySteps([
        [
            "&",
            ["name", "ilike", "Kick"],
            ["amount", ">", 2],
        ],
    ]);
});

test("form: changing the mode to any shows the OR connector", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await click(".o_expression_add_condition");
    await animationFrame();
    await contains(".o_expression_mode_select").select("any");
    await animationFrame();
    expect(queryAllTexts(".o_expression_connector")).toEqual(["", "OR"]);
});

test("form: custom logic reports a reference to a missing condition", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await contains(".o_expression_mode_select").select("custom");
    await animationFrame();
    await fieldInput("expr").edit("1 AND 4");
    await animationFrame();
    expect(".o_expression_error").toHaveText("Custom logic refers to condition 4, which does not exist.");
});

test("form: the code editor shows the domain", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await click(".o_expression_code_toggle");
    await animationFrame();
    expect(".o_expression_code").toHaveText('"name"');
});

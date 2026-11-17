import { describe, expect, test } from "@odoo/hoot";
import { collectFieldNames, isHiddenColumn, isInvisible, parseArch, splitColumns } from "@mobile_web/views/arch";

describe.current.tags("mobile");

test("parseArch keeps tags, attributes and element children", () => {
    const node = parseArch(`<list><field name="name" widget="email"/><group><field name="x"/></group></list>`);
    expect(node.tag).toBe("list");
    expect(node.children.length).toBe(2);
    expect(node.children[0].tag).toBe("field");
    expect(node.children[0].attrs.name).toBe("name");
    expect(node.children[0].attrs.widget).toBe("email");
    expect(node.children[1].children[0].attrs.name).toBe("x");
});

test("collectFieldNames finds fields nested in containers and kanban templates", () => {
    const node = parseArch(`
        <kanban>
            <templates><t t-name="card"><div><field name="a"/></div></t></templates>
            <field name="b"/>
            <group><field name="c"/></group>
        </kanban>`);
    expect([...collectFieldNames(node)].sort()).toEqual(["a", "b", "c"]);
});

test("isInvisible recognises the usual truthy spellings only", () => {
    expect(isInvisible({ attrs: { invisible: "1" } })).toBe(true);
    expect(isInvisible({ attrs: { invisible: "True" } })).toBe(true);
    expect(isInvisible({ attrs: { invisible: "0" } })).toBe(false);
    expect(isInvisible({ attrs: {} })).toBe(false);
});

test("isHiddenColumn hides drag handles and column_invisible columns", () => {
    expect(isHiddenColumn({ attrs: { widget: "handle" } })).toBe(true);
    expect(isHiddenColumn({ attrs: { column_invisible: "1" } })).toBe(true);
    expect(isHiddenColumn({ attrs: { invisible: "1" } })).toBe(true);
    expect(isHiddenColumn({ attrs: { name: "x" } })).toBe(false);
});

test("splitColumns prefers the column marked with the mobile_title class", () => {
    const columns = [
        { name: "login_date", attrs: {}, field: { type: "datetime" } },
        { name: "name", attrs: { class: "o_bold mobile_title" }, field: { type: "char" } },
        { name: "email", attrs: {}, field: { type: "char" } },
    ];
    const { primary, secondary } = splitColumns(columns);
    expect(primary.name).toBe("name");
    expect(secondary.map((c) => c.name)).toEqual(["login_date", "email"]);
});

test("splitColumns falls back to the first text-like column when nothing is marked", () => {
    const columns = [
        { name: "create_date", attrs: {}, field: { type: "date" } },
        { name: "partner", attrs: {}, field: { type: "many2one" } },
    ];
    expect(splitColumns(columns).primary.name).toBe("partner");
});

test("splitColumns uses the first column when no column is text-like", () => {
    const columns = [{ name: "amount", attrs: {}, field: { type: "float" } }];
    const { primary, secondary } = splitColumns(columns);
    expect(primary.name).toBe("amount");
    expect(secondary.length).toBe(0);
});

test("splitColumns on no columns returns no primary", () => {
    const { primary, secondary } = splitColumns([]);
    expect(primary).toBe(null);
    expect(secondary.length).toBe(0);
});

import { describe, expect, test } from "@odoo/hoot";
import { parseArch } from "@mobile_web/views/arch";
import { buildLayout } from "@mobile_web/views/form/layout";

describe.current.tags("mobile");

const FIELDS = {
    name: { type: "char", string: "Name" },
    email: { type: "char", string: "E-mail", readonly: true },
    note: { type: "text", string: "Note" },
    active: { type: "boolean", string: "Active" },
};

test("buildLayout turns fields into labelled field blocks", () => {
    const blocks = buildLayout(parseArch(`<form><sheet><field name="name"/></sheet></form>`), FIELDS);
    expect(blocks.length).toBe(1);
    expect(blocks[0].kind).toBe("field");
    expect(blocks[0].name).toBe("name");
    expect(blocks[0].label).toBe("Name");
    expect(blocks[0].readonly).toBe(false);
});

test("buildLayout uses the arch string over the field string and honours readonly", () => {
    const blocks = buildLayout(
        parseArch(`<form><field name="name" string="Full name"/><field name="email"/></form>`),
        FIELDS
    );
    expect(blocks[0].label).toBe("Full name");
    expect(blocks[1].readonly).toBe(true);
});

test("buildLayout skips invisible fields and fields missing from the model", () => {
    const blocks = buildLayout(
        parseArch(`<form><field name="name" invisible="1"/><field name="ghost"/><field name="note"/></form>`),
        FIELDS
    );
    expect(blocks.length).toBe(1);
    expect(blocks[0].name).toBe("note");
});

test("buildLayout groups fields and creates a notebook with pages", () => {
    const blocks = buildLayout(
        parseArch(`
            <form>
                <group><field name="name"/><field name="active"/></group>
                <notebook>
                    <page string="General"><field name="note"/></page>
                    <page string="Hidden" invisible="1"><field name="email"/></page>
                </notebook>
            </form>`),
        FIELDS
    );
    expect(blocks[0].kind).toBe("group");
    expect(blocks[0].children.length).toBe(2);
    expect(blocks[1].kind).toBe("notebook");
    expect(blocks[1].pages.length).toBe(1);
    expect(blocks[1].pages[0].title).toBe("General");
});

test("buildLayout keeps separators with their text and skips buttons", () => {
    const blocks = buildLayout(
        parseArch(`<form><separator string="Info"/><button name="x" type="object" string="Go"/></form>`),
        FIELDS
    );
    expect(blocks.length).toBe(1);
    expect(blocks[0].kind).toBe("separator");
    expect(blocks[0].text).toBe("Info");
});

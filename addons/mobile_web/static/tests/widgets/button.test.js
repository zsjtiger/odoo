import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { Button } from "@mobile_web/widgets/button/button";

describe.current.tags("mobile");

test("the button shows its label", async () => {
    await mountWithCleanup(Button, { props: { label: "Edit", onClick: () => {} } });
    expect(queryOne(".m_button")).toHaveText("Edit");
});

test("compact and danger variants add their classes", async () => {
    await mountWithCleanup(Button, {
        props: { label: "Delete", compact: true, danger: true, onClick: () => {} },
    });
    expect(queryOne("button")).toHaveClass("m_picker_button_compact");
    expect(queryOne("button")).toHaveClass("m_button_danger");
});

test("the caret is shown only when asked for", async () => {
    await mountWithCleanup(Button, { props: { label: "Edit", caret: true, onClick: () => {} } });
    expect(queryOne(".m_picker_caret")).toHaveText("›");
});

test("clicking calls onClick", async () => {
    let clicks = 0;
    await mountWithCleanup(Button, { props: { label: "Go", onClick: () => clicks++ } });
    await click("button");
    expect(clicks).toBe(1);
});

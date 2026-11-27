import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { PickerButton } from "@mobile_web/widgets/picker/picker";

describe.current.tags("mobile");

test("the picker shows its current value", async () => {
    await mountWithCleanup(PickerButton, { props: { value: "Alpha", placeholder: "Select…", onClick: () => {} } });
    expect(queryOne(".m_picker_value")).toHaveText("Alpha");
    expect(queryAll(".m_picker_placeholder").length).toBe(0);
});

test("the picker shows the placeholder when there is no value", async () => {
    await mountWithCleanup(PickerButton, { props: { value: false, placeholder: "Select…", onClick: () => {} } });
    expect(queryOne(".m_picker_placeholder")).toHaveText("Select…");
    expect(queryAll(".m_picker_value").length).toBe(0);
});

test("the caret is always shown", async () => {
    await mountWithCleanup(PickerButton, { props: { value: false, placeholder: "x", onClick: () => {} } });
    expect(queryOne(".m_picker_caret")).toHaveText("›");
});

test("clicking the picker calls onClick", async () => {
    let calls = 0;
    await mountWithCleanup(PickerButton, {
        props: { value: false, placeholder: "x", onClick: () => calls++ },
    });
    await click(".m_picker_button");
    expect(calls).toBe(1);
});

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { Switch } from "@mobile_web/widgets/switch/switch";

describe.current.tags("mobile");

test("the switch shows its label", async () => {
    await mountWithCleanup(Switch, { props: { checked: false, label: "Active", onChange: () => {} } });
    expect(queryOne(".m_switch_label")).toHaveText("Active");
});

test("the checkbox reflects the checked prop", async () => {
    await mountWithCleanup(Switch, { props: { checked: true, label: "Active", onChange: () => {} } });
    expect(queryOne("input[type=checkbox]")).toBeChecked();
});

test("toggling reports the new boolean value", async () => {
    const values = [];
    await mountWithCleanup(Switch, {
        props: { checked: false, label: "Active", onChange: (value) => values.push(value) },
    });
    const input = queryOne("input[type=checkbox]");
    input.checked = true;
    input.dispatchEvent(new Event("change"));
    expect(values).toEqual([true]);
});

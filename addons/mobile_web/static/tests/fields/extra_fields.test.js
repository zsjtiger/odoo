import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { BadgeField, ColorField, JsonField, LabelSelectionField, PasswordField, ProgressBarField } from "@mobile_web/fields/extra_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

const STATES = [
    ["draft", "Draft"],
    ["done", "Done"],
];

function props(type, value, overrides = {}) {
    return fieldProps({
        name: "value",
        field: { type, string: "Value", selection: STATES },
        record: recordOf({ value }),
        ...overrides,
    });
}

test("badge shows the selection label when readonly", async () => {
    await mountWithCleanup(BadgeField, { props: props("selection", "done", { readonly: true }) });
    expect(queryOne(".m_badge")).toHaveText("Done");
});

test("badge shows the name of a many2one value", async () => {
    await mountWithCleanup(BadgeField, { props: props("many2one", [7, "Acme"], { readonly: true }) });
    expect(queryOne(".m_badge")).toHaveText("Acme");
});

test("label_selection is a badge when readonly and a selection when editable", async () => {
    await mountWithCleanup(LabelSelectionField, { props: props("selection", "draft", { readonly: true }) });
    expect(queryAll(".m_badge").length).toBe(1);
    expect(queryOne(".m_badge")).toHaveText("Draft");
});

test("label_selection offers its options when editable", async () => {
    await mountWithCleanup(LabelSelectionField, { props: props("selection", "draft") });
    expect(queryAll(".m_badge").length).toBe(0);
    expect(queryOne(".m_picker_value")).toHaveText("Draft");
});

test("password never shows the value when readonly", async () => {
    await mountWithCleanup(PasswordField, { props: props("char", "s3cret", { readonly: true }) });
    expect(queryOne(".m_field_value")).not.toHaveText("s3cret");
    expect(queryOne(".m_field_value")).toHaveText("••••••");
});

test("password uses a password input when editable and reports the typed value", async () => {
    const values = [];
    await mountWithCleanup(PasswordField, { props: props("char", false, { onChange: (v) => values.push(v) }) });
    const input = queryOne("input[type=password]");
    input.value = "new-secret";
    input.dispatchEvent(new Event("change"));
    expect(values).toEqual(["new-secret"]);
});

test("color shows the swatch and value when readonly", async () => {
    await mountWithCleanup(ColorField, { props: props("char", "#ff0000", { readonly: true }) });
    expect(queryOne(".m_field_value")).toHaveText("#ff0000");
    expect(queryOne(".m_field_color_swatch").style.backgroundColor).toBe("rgb(255, 0, 0)");
});

test("color reports the chosen hex value when editable", async () => {
    const values = [];
    await mountWithCleanup(ColorField, { props: props("char", "#000000", { onChange: (v) => values.push(v) }) });
    const input = queryOne("input[type=color]");
    input.value = "#00ff00";
    input.dispatchEvent(new Event("change"));
    expect(values).toEqual(["#00ff00"]);
});

test("progressbar clamps the percentage into 0..100", async () => {
    await mountWithCleanup(ProgressBarField, { props: props("float", 140, { readonly: true }) });
    expect(queryOne(".m_progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(queryOne(".m_progressbar_label")).toHaveText("100%");
});

test("json shows formatted JSON when readonly", async () => {
    await mountWithCleanup(JsonField, { props: props("json", { a: 1 }, { readonly: true }) });
    expect(queryOne("pre").textContent).toInclude('"a": 1');
});

test("json ignores invalid JSON and saves valid JSON", async () => {
    const values = [];
    await mountWithCleanup(JsonField, { props: props("json", {}, { onChange: (v) => values.push(v) }) });
    const textarea = queryOne("textarea");
    textarea.value = "{not json";
    textarea.dispatchEvent(new Event("change"));
    textarea.value = '{"b": 2}';
    textarea.dispatchEvent(new Event("change"));
    expect(values).toEqual([{ b: 2 }]);
});

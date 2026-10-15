import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { parseArch } from "@mobile_web/views/arch";
import { buildLayout } from "@mobile_web/views/form/layout";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";
import { recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 6; i++) {
        await animationFrame();
    }
}

const SELECTION = [
    ["a", "Option A"],
    ["b", "Option B"],
];

/** 每种控件: 字段定义, 值; 只读时不应再有可以操作的输入或按钮 */
const CASES = [
    { widget: "", field: { type: "char" }, value: "text" },
    { widget: "email", field: { type: "char" }, value: "a@b.com" },
    { widget: "url", field: { type: "char" }, value: "https://odoo.com" },
    { widget: "phone", field: { type: "char" }, value: "+86 10" },
    { widget: "", field: { type: "text" }, value: "multi\nline" },
    { widget: "", field: { type: "html" }, value: "<p>rich</p>" },
    { widget: "", field: { type: "integer" }, value: 3 },
    { widget: "", field: { type: "float" }, value: 2.5 },
    { widget: "", field: { type: "boolean" }, value: true },
    { widget: "", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "", field: { type: "date" }, value: "2024-11-28" },
    { widget: "", field: { type: "datetime" }, value: "2024-11-28 02:30:00" },
    { widget: "", field: { type: "many2one", relation: "res.partner" }, value: [1, "Alpha"] },
    { widget: "", field: { type: "many2many", relation: "res.partner" }, value: [[1, "Alpha"]] },
    { widget: "many2many_checkboxes", field: { type: "many2many", relation: "res.partner" }, value: [[1, "Alpha"]] },
    { widget: "", field: { type: "binary" }, value: { size: 10 } },
    { widget: "image", field: { type: "binary" }, value: { size: 10 } },
    { widget: "color", field: { type: "char" }, value: "#0f9b8e" },
    { widget: "password", field: { type: "char" }, value: "secret" },
    { widget: "progressbar", field: { type: "float" }, value: 40 },
    { widget: "percentage", field: { type: "float" }, value: 0.4 },
    { widget: "float_time", field: { type: "float" }, value: 1.5 },
    { widget: "json", field: { type: "json" }, value: { a: 1 } },
    { widget: "priority", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "radio", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "statusbar", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "badge", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "label_selection", field: { type: "selection", selection: SELECTION }, value: "a" },
    { widget: "one2many", field: { type: "one2many", relation: "res.partner" }, value: [[1, "Alpha"]] },
];

/** 字段中仍然可以操作的元素 (未禁用的输入、按钮、文本域、下拉) */
function enabledControls() {
    return queryAll(".m_form_field input, .m_form_field button, .m_form_field textarea, .m_form_field select").filter(
        (el) => !el.disabled && !el.classList.contains("m_visually_hidden")
    );
}

test("every widget stays read-only in edit mode when the view marks it readonly", async () => {
    const failures = [];
    for (const { widget, field, value } of CASES) {
        const name = "f";
        const attrs = widget ? ` widget="${widget}"` : "";
        const root = parseArch(`<form><field name="${name}"${attrs} readonly="1"/></form>`);
        const blocks = buildLayout(root, { [name]: field });
        const label = `${widget || field.type}`;
        await mountWithCleanup(FormBlocks, {
            props: {
                blocks,
                record: recordOf({ [name]: value }),
                resModel: "res.partner",
                readonly: false,
                invalid: [],
                onFieldChange: () => {},
            },
        });
        await settle();
        if (queryAll(".m_form_field").length !== 1) {
            failures.push(`${label}: field not rendered`);
        }
        const controls = enabledControls();
        if (controls.length) {
            failures.push(`${label}: ${controls.map((el) => el.tagName + "." + el.className).join(", ")}`);
        }
        document.querySelectorAll(".m_form_field").forEach((el) => el.remove());
    }
    expect(failures).toEqual([]);
});

test("the read-only check sees the controls of an editable field", async () => {
    const root = parseArch(`<form><field name="f"/></form>`);
    const blocks = buildLayout(root, { f: { type: "char" } });
    await mountWithCleanup(FormBlocks, {
        props: { blocks, record: recordOf({ f: "text" }), resModel: "res.partner", readonly: false, invalid: [], onFieldChange: () => {} },
    });
    await settle();
    expect(enabledControls().length > 0).toBe(true);
});

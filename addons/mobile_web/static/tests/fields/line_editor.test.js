import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { parseArch } from "@mobile_web/views/arch";
import { buildLayout } from "@mobile_web/views/form/layout";
import { MobileRecord } from "@mobile_web/views/record";
import { LineEditor } from "@mobile_web/fields/line_editor";

describe.current.tags("mobile");

// 明细模型: name 为本模型的普通字段 (可编辑); partner_name 为 item_id.partner_id.name 的关联字段 (只读, 与 O/M 规则一致)
const LINE_FIELDS = {
    name: { type: "char", string: "Name" },
    partner_name: { type: "char", string: "Partner", readonly: true },
};

function mountEditor(data = { name: "Line A", partner_name: "Acme" }) {
    const blocks = buildLayout(parseArch(`<form><field name="name"/><field name="partner_name"/></form>`), LINE_FIELDS);
    return mountWithCleanup(LineEditor, {
        props: {
            title: "Line",
            resModel: "mobile.demo.line",
            blocks,
            record: new MobileRecord(LINE_FIELDS, -1, data),
            fields: LINE_FIELDS,
            onSave: () => {},
            onCancel: () => {},
            onDelete: () => {},
        },
    });
}

test("in the line editor the own fields are editable and related fields are read-only", async () => {
    await mountEditor();
    const inputs = queryAll(".m_line_editor input");
    expect(inputs.length).toBe(1);
    expect(inputs[0]).toHaveValue("Line A");
    expect(inputs[0]).not.toHaveAttribute("readonly");
});

test("a related field in the line editor shows its value without an input", async () => {
    await mountEditor();
    const labels = queryAll(".m_line_editor .m_form_label").map((el) => el.textContent);
    expect(labels).toEqual(["Name", "Partner"]);
    expect(queryAll(".m_line_editor input").some((el) => el.value === "Acme")).toBe(false);
});

import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { One2manyFormField } from "@mobile_web/fields/one2many_form_field";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";
import { MobileRecord } from "@mobile_web/views/record";
import { fieldProps } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

class KeyInfo extends models.Model {
    _name = "mobile.demo.keyinfo";
    product = fields.Char();
    _records = [];
}
defineModels([KeyInfo]);

// 明细的表单视图: 产品(必填) / 关键信息(必填) / 反馈(必填) 分在一个分组中
const FORM_ARCH = `<form><sheet><group><field name="product"/><field name="key_info"/><field name="feedback"/></group></sheet></form>`;
const FORM_FIELDS = {
    product: { type: "char", string: "Product", required: true },
    key_info: {
        type: "selection",
        string: "Key info",
        required: true,
        selection: [
            ["efficacy", "Efficacy"],
            ["safety", "Safety"],
        ],
    },
    feedback: {
        type: "selection",
        string: "Feedback",
        required: true,
        selection: [
            ["positive", "Positive"],
            ["neutral", "Neutral"],
        ],
    },
};

const LINES = {
    1: { id: 1, product: "测试", key_info: "efficacy", feedback: "positive" },
    2: { id: 2, product: "鼓翘颗粒", key_info: "safety", feedback: "neutral" },
};

function mockLines() {
    onRpc("mobile.demo.keyinfo", "get_views", () => ({
        models: { "mobile.demo.keyinfo": { fields: FORM_FIELDS } },
        views: { form: { arch: FORM_ARCH, id: 1 } },
    }));
    onRpc("mobile.demo.keyinfo", "read", ({ args }) => args[0].map((id) => LINES[id]));
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

/** 挂载内嵌明细表单, 返回明细所在的 MobileRecord (可以检查改动与校验) */
async function mountInline({ pairs = [[1, "测试"], [2, "鼓翘颗粒"]], readonly = false } = {}) {
    mockLines();
    const rec = new MobileRecord({ keyinfo_ids: { type: "one2many" } }, 5, { keyinfo_ids: pairs });
    const record = new FieldRecordAdapter({ getRecord: () => rec, onFieldChange: () => {} });
    await mountWithCleanup(One2manyFormField, {
        props: fieldProps({
            name: "keyinfo_ids",
            field: { type: "one2many", string: "Key info", relation: "mobile.demo.keyinfo" },
            readonly,
            record,
        }),
    });
    await settle();
    return rec;
}

test("each line is a card with the fields of the form view", async () => {
    await mountInline();
    expect(queryAll(".m_o2m_card").length).toBe(2);
    const labels = queryAll(".m_o2m_card")[0].querySelectorAll(".m_form_label");
    expect([...labels].map((el) => el.textContent.replace("*", "").trim())).toEqual(["Product", "Key info", "Feedback"]);
    expect(queryAll(".m_o2m_card .m_form_field input")[0]).toHaveValue("测试");
});

test("the field label is replaced by the title and the add button", async () => {
    await mountInline();
    expect(queryOne(".m_o2m_head .m_o2m_title")).toHaveText("Key info");
    expect(queryAll(".m_o2m_head .m_o2m_add").length).toBe(1);
    expect(queryOne(".m_o2m_head .m_o2m_add")).toHaveText("+");
});

test("add shows an empty card right away, without opening an editor page", async () => {
    const rec = await mountInline();
    await click(".m_o2m_add");
    await settle();
    expect(queryAll(".m_o2m_card").length).toBe(3);
    expect(queryAll(".m_line_editor").length).toBe(0);
    // 已有明细没有改动不产生命令, 只有新增的空明细 [0, 0, {}]
    expect(rec.changes.keyinfo_ids).toEqual([[0, 0, {}]]);
});

test("typing in a card records the value on that line", async () => {
    const rec = await mountInline();
    const input = queryAll(".m_o2m_card .m_form_field input")[0];
    input.value = "新产品";
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new Event("change"));
    await settle();
    expect(rec.changes.keyinfo_ids).toEqual([[1, 1, { product: "新产品" }]]);
});

test("removing a card removes its line, saved as a delete command", async () => {
    const rec = await mountInline();
    await click(queryAll(".m_o2m_card_delete")[0]);
    await settle();
    expect(queryAll(".m_o2m_card").length).toBe(1);
    expect(rec.changes.keyinfo_ids).toEqual([[2, 1]]);
});

test("a new empty line fails validation until its required fields are filled", async () => {
    const rec = await mountInline();
    expect(rec.validators.keyinfo_ids()).toBe(true);
    await click(".m_o2m_add");
    await settle();
    expect(rec.validators.keyinfo_ids()).toBe(false);
});

test("in readonly mode there is no add button and no delete button", async () => {
    await mountInline({ readonly: true });
    expect(queryAll(".m_o2m_add").length).toBe(0);
    expect(queryAll(".m_o2m_card_delete").length).toBe(0);
    expect(queryAll(".m_o2m_card").length).toBe(2);
});

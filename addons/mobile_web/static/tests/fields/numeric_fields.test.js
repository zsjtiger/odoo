import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { formatPercentage, formatFloatTime } from "@web/views/fields/formatters";
import { FloatTimeField, PercentageField } from "@mobile_web/fields/numeric_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

/** 模拟用户输入并提交 */
function typeText(input, text) {
    input.value = text;
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new Event("change"));
}

function numericProps(type, value, overrides = {}) {
    return fieldProps({
        name: "amount",
        field: { type, string: "Amount" },
        record: recordOf({ amount: value }),
        ...overrides,
    });
}

test("percentage shows the stored fraction as a percentage when readonly", async () => {
    await mountWithCleanup(PercentageField, {
        props: numericProps("float", 0.5, { readonly: true }),
    });
    expect(queryOne(".m_field_number")).toHaveText(formatPercentage(0.5));
});

test("percentage commits the typed percentage as a fraction", async () => {
    const values = [];
    await mountWithCleanup(PercentageField, {
        props: numericProps("float", false, { record: recordOf({ amount: false }, { onFieldChange: (n, v) => values.push(v) }) }),
    });
    typeText(queryOne("input"), "25");
    expect(values).toEqual([0.25]);
});

test("percentage accepts a trailing percent sign", async () => {
    const values = [];
    await mountWithCleanup(PercentageField, {
        props: numericProps("float", false, { record: recordOf({ amount: false }, { onFieldChange: (n, v) => values.push(v) }) }),
    });
    typeText(queryOne("input"), "40%");
    expect(values).toEqual([0.4]);
});

test("percentage marks an invalid entry and does not commit it", async () => {
    const values = [];
    const record = recordOf({ amount: 0.1 }, { onFieldChange: (n, v) => values.push(v) });
    await mountWithCleanup(PercentageField, { props: numericProps("float", 0.1, { record }) });
    typeText(queryOne("input"), "abc");
    expect(values).toEqual([]);
    expect(record.isFieldInvalid("amount")).toBe(true);
});

test("float time shows hours as hours and minutes when readonly", async () => {
    await mountWithCleanup(FloatTimeField, {
        props: numericProps("float", 1.5, { readonly: true }),
    });
    expect(queryOne(".m_field_number")).toHaveText(formatFloatTime(1.5));
});

test("float time commits typed hours and minutes as decimal hours", async () => {
    const values = [];
    await mountWithCleanup(FloatTimeField, {
        props: numericProps("float", false, { record: recordOf({ amount: false }, { onFieldChange: (n, v) => values.push(v) }) }),
    });
    typeText(queryOne("input"), "2:15");
    expect(values).toEqual([2.25]);
});

test("float time rejects relative operations", async () => {
    const values = [];
    const record = recordOf({ amount: 1 }, { onFieldChange: (n, v) => values.push(v) });
    await mountWithCleanup(FloatTimeField, { props: numericProps("float", 1, { record }) });
    typeText(queryOne("input"), "+=0:30");
    expect(values).toEqual([]);
    expect(record.isFieldInvalid("amount")).toBe(true);
});

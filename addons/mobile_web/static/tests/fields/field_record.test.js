import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";
import { NumberField } from "@mobile_web/fields/basic_fields";

describe.current.tags("mobile");

/** 与表单视图一致的记录适配层 */
function recordOf(data, { fields = {}, onFieldChange = () => {} } = {}) {
    return new FieldRecordAdapter({
        getRecord: () => ({ data, fields, isNew: false }),
        onFieldChange,
    });
}

function numberProps(type, overrides = {}) {
    return {
        name: "value",
        field: { type },
        record: recordOf({ value: false }),
        readonly: false,
        attrs: {},
        onChange: () => {},
        resModel: "res.partner",
        ...overrides,
    };
}

/** 模拟用户输入并提交 */
function typeText(input, text) {
    input.value = text;
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new Event("change"));
}

test("adapter reads the current record data", () => {
    const adapter = recordOf({ name: "Alpha" }, { fields: { name: { type: "char" } } });
    expect(adapter.data.name).toBe("Alpha");
    expect(adapter.fields.name.type).toBe("char");
    expect(adapter.isValid).toBe(true);
});

test("adapter update forwards each value to the form's field change handler", async () => {
    const calls = [];
    const adapter = recordOf({}, { onFieldChange: (name, value) => calls.push([name, value]) });
    await adapter.update({ name: "Beta", age: 3 });
    expect(calls).toEqual([
        ["name", "Beta"],
        ["age", 3],
    ]);
});

test("adapter tracks invalid fields until they are reset", () => {
    const adapter = recordOf({});
    adapter.setInvalidField("value");
    expect(adapter.isValid).toBe(false);
    expect(adapter.isFieldInvalid("value")).toBe(true);
    adapter.resetFieldValidity("value");
    expect(adapter.isValid).toBe(true);
});

test("NumberField commits a parsed float, including thousands separators", async () => {
    const values = [];
    await mountWithCleanup(NumberField, {
        props: numberProps("float", {
            record: recordOf({ value: false }, { onFieldChange: (name, value) => values.push(value) }),
        }),
    });
    typeText(queryOne("input"), "1,234.5");
    expect(values).toEqual([1234.5]);
});

test("NumberField rejects relative operations such as +=2 instead of committing them", async () => {
    const values = [];
    const record = recordOf({ value: 5 }, { onFieldChange: (name, value) => values.push(value) });
    await mountWithCleanup(NumberField, {
        props: numberProps("float", { record }),
    });
    typeText(queryOne("input"), "+=2");
    expect(values).toEqual([]);
    expect(record.isFieldInvalid("value")).toBe(true);
});

test("NumberField keeps an invalid entry out of the record", async () => {
    const values = [];
    const record = recordOf({ value: 5 }, { onFieldChange: (name, value) => values.push(value) });
    await mountWithCleanup(NumberField, {
        props: numberProps("float", { record }),
    });
    typeText(queryOne("input"), "abc");
    expect(values).toEqual([]);
    expect(record.isFieldInvalid("value")).toBe(true);
});

test("NumberField commits an integer, and an empty entry as false", async () => {
    const values = [];
    await mountWithCleanup(NumberField, {
        props: numberProps("integer", {
            record: recordOf({ value: 1 }, { onFieldChange: (name, value) => values.push(value) }),
        }),
    });
    const input = queryOne("input");
    typeText(input, "42");
    typeText(input, "");
    expect(values).toEqual([42, false]);
});

test("NumberField shows the formatted value when readonly", async () => {
    await mountWithCleanup(NumberField, {
        props: numberProps("float", {
            readonly: true,
            record: recordOf({ value: 1234.5 }),
        }),
    });
    expect(queryOne(".m_field_number")).toHaveText("1,234.50");
});

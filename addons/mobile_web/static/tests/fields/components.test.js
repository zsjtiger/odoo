import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { BooleanField, CharField } from "@mobile_web/fields/basic_fields";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";

describe.current.tags("mobile");

/** 与表单视图一致的记录适配层: 字段组件通过它读值、提交值 */
function recordOf(data, { fields = {}, onFieldChange = () => {} } = {}) {
    return new FieldRecordAdapter({
        getRecord: () => ({ data, fields, isNew: false }),
        onFieldChange,
    });
}


/** 挂载字段组件时的公共 props */
function fieldProps(overrides) {
    return {
        name: "active",
        field: { type: "boolean", string: "Active" },
        record: { data: {} },
        readonly: false,
        attrs: {},
        onChange: () => {},
        ...overrides,
    };
}

test("BooleanField shows Yes/No when readonly", async () => {
    await mountWithCleanup(BooleanField, {
        props: fieldProps({ readonly: true, record: { data: { active: true } } }),
    });
    expect(queryOne(".m_field_value")).toHaveText("Yes");
});

test("BooleanField shows No for a false value", async () => {
    await mountWithCleanup(BooleanField, {
        props: fieldProps({ readonly: true, record: { data: { active: false } } }),
    });
    expect(queryOne(".m_field_value")).toHaveText("No");
});

test("BooleanField switch reports the new value when toggled", async () => {
    const changes = [];
    await mountWithCleanup(BooleanField, {
        props: fieldProps({
            record: { data: { active: false } },
            onChange: (value) => changes.push(value),
        }),
    });
    await click(".m_switch");
    expect(changes).toEqual([true]);
});

test("CharField renders an email as a mailto link when readonly", async () => {
    await mountWithCleanup(CharField, {
        props: fieldProps({
            name: "email",
            field: { type: "char" },
            readonly: true,
            attrs: { widget: "email" },
            record: recordOf({ email: "a@b.c" }),
        }),
    });
    expect(queryOne("a.m_field_link")).toHaveAttribute("href", "mailto:a@b.c");
});

test("CharField without a value shows nothing when readonly", async () => {
    await mountWithCleanup(CharField, {
        props: fieldProps({
            name: "name",
            field: { type: "char" },
            readonly: true,
            record: recordOf({ name: false }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText("");
});

test("CharField commits the trimmed text, or false when empty", async () => {
    const values = [];
    await mountWithCleanup(CharField, {
        props: fieldProps({
            name: "name",
            field: { type: "char" },
            record: recordOf({ name: "x" }, {
                fields: { name: { type: "char" } },
                onFieldChange: (name, value) => values.push(value),
            }),
        }),
    });
    const input = queryOne("input");
    for (const text of ["  hello  ", "   "]) {
        input.value = text;
        input.dispatchEvent(new Event("input"));
        input.dispatchEvent(new Event("change"));
    }
    expect(values).toEqual(["hello", false]);
});

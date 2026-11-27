import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { deserializeDate, deserializeDateTime } from "@web/core/data/l10n/dates";
import { formatDate } from "@web/views/fields/formatters";
import {
    DateField,
    DateTimeField,
    FallbackField,
    HtmlField,
    SelectionField,
    TextField,
} from "@mobile_web/fields/basic_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

/** 模拟用户输入并提交 */
function typeText(input, text) {
    input.value = text;
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new Event("change"));
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("text shows the value as a paragraph when readonly", async () => {
    await mountWithCleanup(TextField, {
        props: fieldProps({
            name: "note",
            field: { type: "text" },
            readonly: true,
            record: recordOf({ note: "Line one" }),
        }),
    });
    expect(queryOne("p.m_field_multiline")).toHaveText("Line one");
});

test("text commits the edited value, or false when cleared", async () => {
    const values = [];
    await mountWithCleanup(TextField, {
        props: fieldProps({
            name: "note",
            field: { type: "text" },
            record: recordOf({ note: "" }),
            onChange: (value) => values.push(value),
        }),
    });
    const textarea = queryOne("textarea");
    textarea.value = "Hello";
    textarea.dispatchEvent(new Event("change"));
    textarea.value = "";
    textarea.dispatchEvent(new Event("change"));
    expect(values).toEqual(["Hello", false]);
});

test("html is shown as formatted content in a form", async () => {
    await mountWithCleanup(HtmlField, {
        props: fieldProps({
            name: "body",
            field: { type: "html" },
            readonly: true,
            record: recordOf({ body: "<p>Hello <b>world</b></p>" }),
        }),
    });
    expect(queryOne(".m_field_html b")).toHaveText("world");
    expect(queryOne(".m_field_html")).toHaveText("Hello world");
});

test("selection shows the label of the current option", async () => {
    await mountWithCleanup(SelectionField, {
        props: fieldProps({
            name: "state",
            field: {
                type: "selection",
                string: "State",
                selection: [
                    ["draft", "Draft"],
                    ["done", "Done"],
                ],
            },
            readonly: true,
            record: recordOf({ state: "done" }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText("Done");
});

test("selection reports the chosen option value", async () => {
    const values = [];
    await mountWithCleanup(SelectionField, {
        props: fieldProps({
            name: "state",
            field: {
                type: "selection",
                string: "State",
                selection: [
                    ["draft", "Draft"],
                    ["done", "Done"],
                ],
            },
            record: recordOf({ state: false }),
            onChange: (value) => values.push(value),
        }),
    });
    expect(queryOne(".m_picker_placeholder")).toHaveText("Select…");
    await click(".m_picker_button");
    await settle();
    await click(queryAll(".m_sheet_item:not(.m_sheet_item_clear)")[1]);
    expect(values).toEqual(["done"]);
});

test("date shows the locale date when readonly", async () => {
    await mountWithCleanup(DateField, {
        props: fieldProps({
            name: "date",
            field: { type: "date" },
            readonly: true,
            record: recordOf({ date: "2024-01-05" }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText(formatDate(deserializeDate("2024-01-05")));
});

test("date commits the picked day, or false when cleared", async () => {
    const values = [];
    await mountWithCleanup(DateField, {
        props: fieldProps({
            name: "date",
            field: { type: "date" },
            record: recordOf({ date: false }),
            onChange: (value) => values.push(value),
        }),
    });
    const input = queryOne("input[type=date]");
    typeText(input, "2024-02-10");
    typeText(input, "");
    expect(values).toEqual(["2024-02-10", false]);
});

test("datetime shows the locale date and time when readonly", async () => {
    const stored = "2024-01-05 08:30:00";
    await mountWithCleanup(DateTimeField, {
        props: fieldProps({
            name: "when",
            field: { type: "datetime" },
            readonly: true,
            record: recordOf({ when: stored }),
        }),
    });
    expect(queryOne(".m_field_value").textContent).not.toBe("");
});

test("datetime commits a value in the server format, or false when cleared", async () => {
    const values = [];
    await mountWithCleanup(DateTimeField, {
        props: fieldProps({
            name: "when",
            field: { type: "datetime" },
            record: recordOf({ when: false }),
            onChange: (value) => values.push(value),
        }),
    });
    const input = queryOne("input[type=datetime-local]");
    typeText(input, "2024-02-10T14:45");
    typeText(input, "");
    expect(values.length).toBe(2);
    // 服务端格式为 UTC, 转回本地时间后应与输入一致(与时区无关)
    expect(deserializeDateTime(values[0]).toFormat("yyyy-LL-dd'T'HH:mm")).toBe("2024-02-10T14:45");
    expect(values[1]).toBe(false);
});

test("fallback shows the raw value for unsupported field types", async () => {
    await mountWithCleanup(FallbackField, {
        props: fieldProps({
            name: "geo",
            field: { type: "geo" },
            readonly: true,
            record: recordOf({ geo: "POINT(1 2)" }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText("POINT(1 2)");
});

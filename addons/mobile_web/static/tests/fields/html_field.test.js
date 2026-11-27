import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { HtmlField } from "@mobile_web/fields/basic_fields";
import { sanitizeHtml } from "@mobile_web/fields/html_sanitize";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

function htmlProps(value, overrides = {}) {
    return fieldProps({
        name: "body",
        field: { type: "html", string: "Body" },
        record: recordOf({ body: value }),
        readonly: true,
        ...overrides,
    });
}

test("sanitize keeps formatting and text", () => {
    expect(sanitizeHtml("<p><strong>Bold</strong> text</p>")).toBe("<p><strong>Bold</strong> text</p>");
});

test("sanitize removes scripts with their content", () => {
    expect(sanitizeHtml("<p>a</p><script>alert(1)</script>")).toBe("<p>a</p>");
});

test("sanitize removes event handlers and inline styles", () => {
    expect(sanitizeHtml('<p onclick="x()" style="color:red">a</p>')).toBe("<p>a</p>");
});

test("sanitize drops javascript and data links, even when obfuscated", () => {
    expect(sanitizeHtml('<a href="javascript:alert(1)">x</a>')).toBe("<a>x</a>");
    expect(sanitizeHtml('<a href="java\tscript:alert(1)">x</a>')).toBe("<a>x</a>");
});

test("sanitize keeps safe links and opens them in a new tab", () => {
    expect(sanitizeHtml('<a href="https://example.com">x</a>')).toBe(
        '<a href="https://example.com" target="_blank" rel="noopener noreferrer">x</a>'
    );
});

test("sanitize keeps only raster images from data URIs", () => {
    expect(sanitizeHtml('<img src="data:image/png;base64,AAAA" alt="a">')).toBe(
        '<img src="data:image/png;base64,AAAA" alt="a">'
    );
    expect(sanitizeHtml('<img src="data:text/html;base64,AAAA">')).toBe("<img>");
});

test("sanitize unwraps unknown tags but keeps their text", () => {
    expect(sanitizeHtml("<font>hi</font>")).toBe("hi");
});

test("html shows the formatted content when readonly", async () => {
    await mountWithCleanup(HtmlField, {
        props: htmlProps("<p><strong>Bold</strong> text</p><script>alert(1)</script>"),
    });
    expect(queryOne(".m_field_html strong")).toHaveText("Bold");
    expect(queryAll("script").length).toBe(0);
});

test("html shows None when empty", async () => {
    await mountWithCleanup(HtmlField, { props: htmlProps(false) });
    expect(queryOne(".m_field_empty")).toHaveText("None");
});

test("html in a list cell shows plain text only", async () => {
    await mountWithCleanup(HtmlField, {
        props: htmlProps("<p><strong>Bold</strong> text</p><script>alert(1)</script>", { compact: true }),
    });
    expect(queryAll(".m_field_html").length).toBe(0);
    expect(queryOne(".m_field_value")).toHaveText("Bold text");
});

test("html shows the desktop hint when editable", async () => {
    await mountWithCleanup(HtmlField, { props: htmlProps("<p>a</p>", { readonly: false }) });
    expect(queryOne(".m_field_hint")).toHaveText("Edit rich text on the desktop");
});

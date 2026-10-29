import { describe, expect, test } from "@odoo/hoot";
import "@mobile_web/views/index";
import { mobileFieldRegistry, mobileViewRegistry } from "@mobile_web/views/registries";
import { getFieldWidget } from "@mobile_web/fields/index";
import { fieldTexts } from "@mobile_web/core/texts";
import { patchTranslations } from "@web/../tests/_framework/translation_test_helpers";
import { CharField, DateField, NumberField } from "@mobile_web/fields/basic_fields";
import { BinaryField, Many2oneField } from "@mobile_web/fields/relational_fields";
import { FallbackField } from "@mobile_web/fields/basic_fields";
import { MobileFormView } from "@mobile_web/views/form/mobile_form_view";
import { MobileKanbanView } from "@mobile_web/views/kanban/mobile_kanban_view";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";

describe.current.tags("mobile");

test("the three mobile views are registered by view type", () => {
    expect(mobileViewRegistry.get("list")).toBe(MobileListView);
    expect(mobileViewRegistry.get("kanban")).toBe(MobileKanbanView);
    expect(mobileViewRegistry.get("form")).toBe(MobileFormView);
});

test("field widgets are registered by type and by widget name", () => {
    expect(mobileFieldRegistry.get("char")).toBe(CharField);
    expect(mobileFieldRegistry.get("email")).toBe(CharField);
    expect(mobileFieldRegistry.get("date")).toBe(DateField);
    expect(mobileFieldRegistry.get("many2one")).toBe(Many2oneField);
    expect(mobileFieldRegistry.get("image")).toBe(BinaryField);
    expect(mobileFieldRegistry.get("integer")).toBe(NumberField);
});

test("the texts object holds translatable strings for the shared widgets", () => {
    // 翻译加载后, 惰性字符串才能转换为文本
    patchTranslations({});
    for (const key of ["yes", "no", "select", "cancel", "confirm", "search", "loading", "noMatch"]) {
        expect(String(fieldTexts[key]).length > 0).toBe(true);
    }
});

test("getFieldWidget prefers the arch widget over the field type", () => {
    expect(getFieldWidget({ widget: "email" }, { type: "char" })).toBe(CharField);
    expect(getFieldWidget({ widget: "image" }, { type: "char" })).toBe(BinaryField);
});

test("getFieldWidget falls back to the field type without a known widget", () => {
    expect(getFieldWidget({ widget: "unknown" }, { type: "integer" })).toBe(NumberField);
    expect(getFieldWidget({}, { type: "many2one" })).toBe(Many2oneField);
});

test("getFieldWidget uses the fallback widget for unsupported types", () => {
    expect(getFieldWidget({}, { type: "geo" })).toBe(FallbackField);
});

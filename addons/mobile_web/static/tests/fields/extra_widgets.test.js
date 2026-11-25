import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { BooleanField } from "@mobile_web/fields/basic_fields";
import { BadgesSelectionField } from "@mobile_web/fields/selection_fields";
import { FloatToggleField } from "@mobile_web/fields/numeric_fields";
import { HandleField, ImageUrlField } from "@mobile_web/fields/extra_fields";
import { Many2manyTagsAvatarField, Many2oneAvatarField } from "@mobile_web/fields/relational_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";
import { formatFloat } from "@web/views/fields/formatters";

describe.current.tags("mobile");

const STATES = [
    ["draft", "Draft"],
    ["done", "Done"],
    ["cancel", "Cancelled"],
];

function props(type, value, overrides = {}) {
    return fieldProps({
        name: "value",
        field: { type, string: "Value", selection: STATES },
        record: recordOf({ value }),
        ...overrides,
    });
}

test("boolean_toggle uses the boolean switch", () => {
    expect(mobileFieldRegistry.get("boolean_toggle")).toBe(BooleanField);
});

test("many2many_tags is the same tag field as many2many", () => {
    expect(mobileFieldRegistry.get("many2many_tags")).toBe(mobileFieldRegistry.get("many2many"));
});

test("badges_selection shows every option as a button and marks the current one", async () => {
    await mountWithCleanup(BadgesSelectionField, { props: props("selection", "done") });
    const buttons = queryAll(".m_badge_option");
    expect(buttons.length).toBe(3);
    expect(queryOne(".m_badge_option_active")).toHaveText("Done");
});

test("badges_selection calls onChange with the clicked option", async () => {
    const calls = [];
    await mountWithCleanup(BadgesSelectionField, {
        props: props("selection", "draft", { onChange: (value) => calls.push(value) }),
    });
    await click(queryAll(".m_badge_option")[2]);
    expect(calls).toEqual(["cancel"]);
});

test("badges_selection shows the label when readonly", async () => {
    await mountWithCleanup(BadgesSelectionField, { props: props("selection", "cancel", { readonly: true }) });
    expect(queryOne(".m_field_value")).toHaveText("Cancelled");
});

test("float_toggle shows the value multiplied by factor", async () => {
    await mountWithCleanup(FloatToggleField, {
        props: props("float", 2, { readonly: true, attrs: { options: "{'factor': 10}" } }),
    });
    expect(queryOne(".m_field_value").textContent.trim()).toBe(formatFloat(20));
});

test("float_toggle cycles through the range and stores value / factor", async () => {
    const calls = [];
    await mountWithCleanup(FloatToggleField, {
        props: props("float", 0.2, {
            attrs: { options: "{'range': [1, 2, 3], 'factor': 10}" },
            onChange: (value) => calls.push(value),
        }),
    });
    // displayed 2 (= 0.2 * 10) is range[1] -> next is range[2] = 3 -> stored 3 / 10
    await click(queryOne(".m_float_toggle"));
    expect(calls).toEqual([0.3]);
});

test("handle renders nothing visible", async () => {
    await mountWithCleanup(HandleField, { props: props("integer", 5) });
    expect(queryOne(".m_handle_hidden")).toBeTruthy();
    expect(queryAll(".m_field_value").length).toBe(0);
});

test("image_url shows the image when readonly", async () => {
    await mountWithCleanup(ImageUrlField, {
        props: props("char", "https://example.com/a.png", { readonly: true }),
    });
    expect(queryOne(".m_image_url_preview").getAttribute("src")).toBe("https://example.com/a.png");
});

test("image_url sends the typed url as the new value", async () => {
    const calls = [];
    await mountWithCleanup(ImageUrlField, {
        props: props("char", false, { onChange: (value) => calls.push(value) }),
    });
    const input = queryOne("input.o_input");
    input.value = " https://example.com/b.png ";
    input.dispatchEvent(new Event("change"));
    expect(calls).toEqual(["https://example.com/b.png"]);
});

test("many2one_avatar shows the avatar of the related record when readonly", async () => {
    await mountWithCleanup(Many2oneAvatarField, {
        props: fieldProps({
            name: "partner_id",
            field: { type: "many2one", string: "Partner", relation: "res.partner" },
            record: recordOf({ partner_id: [7, "Acme"] }),
            readonly: true,
        }),
    });
    expect(queryOne(".m_avatar").getAttribute("src")).toBe("/web/image/res.partner/7/avatar_128");
});

test("many2many_tags_avatar shows an avatar in every tag", async () => {
    await mountWithCleanup(Many2manyTagsAvatarField, {
        props: fieldProps({
            name: "user_ids",
            field: { type: "many2many", string: "Users", relation: "res.users" },
            record: recordOf({ user_ids: [[3, "Ann"], [4, "Bob"]] }),
            readonly: true,
        }),
    });
    expect(queryAll(".m_tag_avatar").length).toBe(2);
    expect(queryAll(".m_tag_avatar .m_avatar")[1].getAttribute("src")).toBe("/web/image/res.users/4/avatar_128");
});

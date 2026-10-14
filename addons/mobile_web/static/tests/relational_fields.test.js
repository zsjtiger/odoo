import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { BinaryField, Many2manyField, Many2oneField, One2manyField } from "@mobile_web/views/fields/relational_fields";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

/** 等待 name_search 的结果渲染到弹层中 */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("many2one shows the related name when readonly", async () => {
    await mountWithCleanup(Many2oneField, {
        props: fieldProps({
            name: "parent_id",
            field: { type: "many2one", string: "Parent", relation: "res.partner" },
            readonly: true,
            record: recordOf({ parent_id: [1, "Alpha"] }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText("Alpha");
});

test("many2one shows the placeholder when empty", async () => {
    await mountWithCleanup(Many2oneField, {
        props: fieldProps({
            name: "parent_id",
            field: { type: "many2one", string: "Parent", relation: "res.partner" },
            record: recordOf({ parent_id: false }),
        }),
    });
    expect(queryOne(".m_picker_placeholder")).toHaveText("Select…");
});

test("many2one picks a record from the name search and reports [id, name]", async () => {
    const values = [];
    onRpc("res.partner", "name_search", () => [
        [1, "Alpha"],
        [2, "Beta"],
    ]);
    await mountWithCleanup(Many2oneField, {
        props: fieldProps({
            name: "parent_id",
            field: { type: "many2one", string: "Parent", relation: "res.partner" },
            record: recordOf({ parent_id: false }),
            onChange: (value) => values.push(value),
        }),
    });
    await click(".m_picker_button");
    await settle();
    expect(queryAll(".m_sheet_item:not(.m_sheet_item_clear)").length).toBe(2);
    await click(queryAll(".m_sheet_item:not(.m_sheet_item_clear)")[1]);
    expect(values).toEqual([[2, "Beta"]]);
});

test("many2many shows each related name, falling back to the id", async () => {
    await mountWithCleanup(Many2manyField, {
        props: fieldProps({
            name: "tag_ids",
            field: { type: "many2many", string: "Tags", relation: "res.partner" },
            record: recordOf({ tag_ids: [[1, "Alpha"], [3, null]] }),
        }),
    });
    const tags = queryAll(".m_tag").map((el) => el.textContent);
    expect(tags).toEqual(["Alpha", "#3"]);
});

test("many2many reports the full selection on confirm", async () => {
    const values = [];
    onRpc("res.partner", "name_search", () => [
        [1, "Alpha"],
        [2, "Beta"],
    ]);
    await mountWithCleanup(Many2manyField, {
        props: fieldProps({
            name: "tag_ids",
            field: { type: "many2many", string: "Tags", relation: "res.partner" },
            record: recordOf({ tag_ids: [[1, "Alpha"]] }),
            onChange: (value) => values.push(value),
        }),
    });
    await click(".m_picker_button");
    await settle();
    await click(queryAll(".m_sheet_item:not(.m_sheet_item_clear)")[1]);
    await click(".m_sheet_btn_primary");
    expect(values).toEqual([[[1, "Alpha"], [2, "Beta"]]]);
});

test("one2many previews five lines and counts the rest", async () => {
    const lines = Array.from({ length: 7 }, (_, i) => [i + 1, `Line ${i + 1}`]);
    await mountWithCleanup(One2manyField, {
        props: fieldProps({
            name: "line_ids",
            field: { type: "one2many", string: "Lines", relation: "res.partner" },
            readonly: true,
            record: recordOf({ line_ids: lines }),
        }),
    });
    expect(queryAll(".m_one2many_list li:not(.m_field_empty)").length).toBe(5);
    expect(queryOne(".m_one2many_list .m_field_empty")).toHaveText("2 more lines");
});

test("one2many shows None when there are no lines", async () => {
    await mountWithCleanup(One2manyField, {
        props: fieldProps({
            name: "line_ids",
            field: { type: "one2many", string: "Lines", relation: "res.partner" },
            readonly: true,
            record: recordOf({ line_ids: [] }),
        }),
    });
    expect(queryOne(".m_one2many_list")).toHaveText("None");
});

test("binary shows the stored image from /web/image when nothing is pending", async () => {
    await mountWithCleanup(BinaryField, {
        props: fieldProps({
            name: "image_1920",
            field: { type: "binary", string: "Image" },
            readonly: true,
            record: recordOf({ image_1920: "AAAA" }, { resId: 3 }),
        }),
    });
    expect(queryOne("img.m_field_image")).toHaveAttribute("src", "/web/image/res.partner/3/image_1920");
});

test("binary shows a just-selected image as a data URI, without a server round trip", async () => {
    await mountWithCleanup(BinaryField, {
        props: fieldProps({
            name: "image_1920",
            field: { type: "binary", string: "Image" },
            record: recordOf({ image_1920: "BBBB" }, { resId: 3, changes: { image_1920: "BBBB" } }),
        }),
    });
    expect(queryOne("img.m_field_image")).toHaveAttribute("src", "data:image/*;base64,BBBB");
});

test("binary clears the value when the delete button is pressed", async () => {
    const values = [];
    await mountWithCleanup(BinaryField, {
        props: fieldProps({
            name: "image_1920",
            field: { type: "binary", string: "Image" },
            record: recordOf({ image_1920: "AAAA" }, { resId: 3 }),
            onChange: (value) => values.push(value),
        }),
    });
    await click(".m_button_danger");
    expect(values).toEqual([false]);
});

test("binary shows None when readonly and empty", async () => {
    await mountWithCleanup(BinaryField, {
        props: fieldProps({
            name: "image_1920",
            field: { type: "binary", string: "Image" },
            readonly: true,
            record: recordOf({ image_1920: false }, { resId: 3 }),
        }),
    });
    expect(queryOne(".m_field_empty")).toHaveText("None");
    expect(queryAll("img.m_field_image").length).toBe(0);
});

import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { MobileCascadeSheet } from "@mobile_web/widgets/cascade_sheet/cascade_sheet";

describe.current.tags("mobile");

class Region extends models.Model {
    _name = "mobile.demo.region";
    name = fields.Char();
    parent_id = fields.Many2one({ relation: "mobile.demo.region" });
    _records = [];
}
defineModels([Region]);

// 省 > 市 > 区: 北京市(1) > 北京市(2) > 东城区(3), 西城区(4); 广东省(5) > 广州市(6)
const REGIONS = [
    { id: 1, name: "北京市", parent_id: false, child_ids: [2] },
    { id: 2, name: "北京市", parent_id: [1, "北京市"], child_ids: [3, 4] },
    { id: 3, name: "东城区", parent_id: [2, "北京市"], child_ids: [] },
    { id: 4, name: "西城区", parent_id: [2, "北京市"], child_ids: [] },
    { id: 5, name: "广东省", parent_id: false, child_ids: [6] },
    { id: 6, name: "广州市", parent_id: [5, "广东省"], child_ids: [] },
];

function mockRegions() {
    onRpc("mobile.demo.region", "search_read", ({ kwargs }) => {
        const parent = kwargs.domain[0][2];
        return REGIONS.filter((r) => (r.parent_id ? r.parent_id[0] : false) === parent).map(
            ({ id, name, child_ids }) => ({ id, name, child_ids })
        );
    });
    onRpc("mobile.demo.region", "read", ({ args }) =>
        REGIONS.filter((r) => args[0].includes(r.id)).map(({ id, name, parent_id }) => ({ id, name, parent_id }))
    );
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

function itemNames() {
    return queryAll(".m_cascade_sheet .m_sheet_item_name").map((el) => el.textContent);
}

function tabNames() {
    return queryAll(".m_cascade_sheet .m_cascade_tab").map((el) => el.textContent);
}

async function mountSheet(selected = [], onConfirm = () => {}) {
    mockRegions();
    await mountWithCleanup(MobileCascadeSheet, {
        props: { title: "Region", relation: "mobile.demo.region", selected, onConfirm, onClose: () => {} },
    });
    await settle();
}

test("without a value the top level is listed and only the root tab is shown", async () => {
    await mountSheet();
    expect(itemNames()).toEqual(["北京市", "广东省"]);
    expect(queryAll(".m_cascade_tab").length).toBe(1);
    expect(queryOne(".m_cascade_tab")).toHaveClass("is_active");
});

test("clicking an item with children goes into the next level and adds a tab", async () => {
    await mountSheet();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    expect(itemNames()).toEqual(["北京市"]);
    expect(tabNames().length).toBe(2);
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    expect(itemNames()).toEqual(["东城区", "西城区"]);
    expect(tabNames().length).toBe(3);
    expect(queryOne(".m_cascade_tab:last-child")).toHaveClass("is_active");
});

test("clicking a tab goes back to that level", async () => {
    await mountSheet();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    await click(queryAll(".m_cascade_tab")[1]);
    await settle();
    expect(itemNames()).toEqual(["北京市"]);
    await click(queryAll(".m_cascade_tab")[0]);
    await settle();
    expect(itemNames()).toEqual(["北京市", "广东省"]);
    expect(tabNames().length).toBe(1);
});

test("confirm returns the item that was clicked last", async () => {
    const confirmed = [];
    await mountSheet([], (selected) => confirmed.push(selected));
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await settle();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[0]);
    await click(queryOne(".m_sheet_btn_primary"));
    expect(confirmed).toEqual([[{ id: 3, name: "北京市 北京市 东城区" }]]);
});

test("an existing value opens at its level with the value checked", async () => {
    await mountSheet([{ id: 3, name: "北京市 北京市 东城区" }]);
    expect(itemNames()).toEqual(["东城区", "西城区"]);
    expect(queryAll(".m_cascade_sheet .m_sheet_check").length).toBe(1);
    expect(tabNames().slice(1)).toEqual(["北京市", "北京市"]);
    expect(queryOne(".m_cascade_tab:last-child")).toHaveClass("is_active");
});

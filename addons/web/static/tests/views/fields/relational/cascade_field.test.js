import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { CascadeField } from "@web/views/fields/relational/cascade/cascade_field";

describe.current.tags("headless");

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

/** 挂载级联控件, 返回记录的改动列表 */
async function mountCascade(value = false) {
    mockRegions();
    const updates = [];
    const record = {
        data: { region_id: value },
        fields: { region_id: { type: "many2one", string: "Region", relation: "mobile.demo.region" } },
        update: (vals) => updates.push(vals),
    };
    await mountWithCleanup(CascadeField, { props: { name: "region_id", record, readonly: false } });
    return updates;
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("the cascade field opens a dialog listing the top level regions", async () => {
    await mountCascade();
    await click(".o_cascade_field");
    await settle();
    const names = queryAll(".modal .list-group-item span:first-child").map((el) => el.textContent);
    expect(names).toEqual(["北京市", "广东省"]);
});

test("drilling down to a district and confirming stores the full path name", async () => {
    const updates = await mountCascade();
    await click(".o_cascade_field");
    await settle();
    await click(queryAll(".modal .list-group-item")[0]);
    await settle();
    await click(queryAll(".modal .list-group-item")[0]);
    await settle();
    await click(queryAll(".modal .list-group-item")[1]);
    await settle();
    await click(queryOne(".modal .btn-primary"));
    await settle();
    expect(updates).toEqual([{ region_id: { id: 4, display_name: "北京市 北京市 西城区" } }]);
});

test("the current value is shown as its full path", async () => {
    await mountCascade({ id: 3, display_name: "北京市 北京市 东城区" });
    expect(queryOne(".o_cascade_field")).toHaveText("北京市 北京市 东城区");
});

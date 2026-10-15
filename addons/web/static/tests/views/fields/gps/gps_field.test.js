import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { GpsField } from "@web/views/fields/gps/gps_field";

describe.current.tags("headless");

function mockRecord(value = false) {
    const updates = [];
    const record = {
        data: { gps_id: value },
        fields: { gps_id: { type: "many2one", string: "Location", relation: "gps" } },
        resModel: "mobile.demo.item",
        resId: 1,
        update: (vals) => updates.push(vals),
    };
    return { record, updates };
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("an empty location field asks to get the location", async () => {
    onRpc("gps", "get_map_config", () => ({}));
    const { record } = mockRecord();
    await mountWithCleanup(GpsField, { props: { name: "gps_id", record, readonly: false } });
    expect(queryOne(".o_gps_field")).toHaveText("Get location");
});

test("confirming manual coordinates creates a location owned by the record", async () => {
    onRpc("gps", "get_map_config", () => ({}));
    const created = [];
    onRpc("gps", "create", ({ args }) => {
        created.push(args[0][0]);
        return [71];
    });
    onRpc("gps", "read", () => [{ id: 71, display_name: "北京市朝阳区建国路 88 号" }]);
    const { record, updates } = mockRecord();
    await mountWithCleanup(GpsField, { props: { name: "gps_id", record, readonly: false } });
    await click(".o_gps_field");
    await settle();
    const inputs = queryAll(".modal input");
    // 地址、纬度、经度 (地址是第一个文本框; 纬度与经度是两个数字框)
    inputs[1].value = "北京市朝阳区建国路 88 号";
    inputs[1].dispatchEvent(new Event("input"));
    inputs[2].value = "39.9042";
    inputs[2].dispatchEvent(new Event("input"));
    inputs[3].value = "116.4074";
    inputs[3].dispatchEvent(new Event("input"));
    await settle();
    await click(queryOne(".modal .btn-primary"));
    await settle();
    expect(created).toEqual([
        {
            address: "北京市朝阳区建国路 88 号",
            latitude: 39.9042,
            longitude: 116.4074,
            source: "manual",
            res_model: "mobile.demo.item",
            res_field: "gps_id",
            res_id: 1,
        },
    ]);
    expect(updates).toEqual([{ gps_id: { id: 71, display_name: "北京市朝阳区建国路 88 号" } }]);
});

test("confirm with an out of range latitude shows an error and saves nothing", async () => {
    onRpc("gps", "get_map_config", () => ({}));
    let calls = 0;
    onRpc("gps", "create", () => {
        calls += 1;
        return [1];
    });
    const { record, updates } = mockRecord();
    await mountWithCleanup(GpsField, { props: { name: "gps_id", record, readonly: false } });
    await click(".o_gps_field");
    await settle();
    const inputs = queryAll(".modal input");
    inputs[2].value = "95";
    inputs[2].dispatchEvent(new Event("input"));
    inputs[3].value = "10";
    inputs[3].dispatchEvent(new Event("input"));
    await settle();
    await click(queryOne(".modal .btn-primary"));
    await settle();
    expect(calls).toBe(0);
    expect(updates).toEqual([]);
    expect(queryOne(".modal .text-danger")).toHaveText("The latitude is missing or out of range.");
});

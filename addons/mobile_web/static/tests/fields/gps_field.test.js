import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { GpsField } from "@mobile_web/fields/gps_field";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

test("an empty location field asks to get the location", async () => {
    onRpc("gps", "get_map_config", () => ({}));
    await mountWithCleanup(GpsField, {
        props: fieldProps({
            name: "gps_id",
            field: { type: "many2one", string: "Location", relation: "gps" },
            resModel: "mobile.demo.item",
            record: recordOf({ gps_id: false }),
        }),
    });
    await animationFrame();
    expect(queryOne(".m_picker_placeholder")).toHaveText("Get location");
});

test("a read-only location shows its address and the coordinates of the point", async () => {
    onRpc("gps", "get_map_config", () => ({}));
    onRpc("gps", "read", () => [{ id: 7, address: "北京市朝阳区建国路 88 号", latitude: 39.9042, longitude: 116.4074 }]);
    await mountWithCleanup(GpsField, {
        props: fieldProps({
            name: "gps_id",
            field: { type: "many2one", string: "Location", relation: "gps" },
            resModel: "mobile.demo.item",
            readonly: true,
            record: recordOf({ gps_id: [7, "北京市朝阳区建国路 88 号"] }),
        }),
    });
    await animationFrame();
    await animationFrame();
    expect(queryOne(".m_field_value")).toHaveText("北京市朝阳区建国路 88 号");
    expect(queryOne(".o_gps_preview_coords")).toHaveText("39.904200, 116.407400");
});

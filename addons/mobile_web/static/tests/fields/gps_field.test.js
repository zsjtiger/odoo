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

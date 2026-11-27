import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { GpsPreview } from "@web/views/fields/gps/gps_preview";

describe.current.tags("headless");

const LOCATION = { address: "北京市朝阳区建国路 88 号", latitude: 39.9042, longitude: 116.4074 };

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("without a map key the preview lists the coordinates and loads no map", async () => {
    await mountWithCleanup(GpsPreview, { props: { location: LOCATION, mapConfig: {}, height: 160 } });
    await settle();
    expect(queryOne(".o_gps_preview_coords")).toHaveText("39.904200, 116.407400");
    expect(queryAll(".o_gps_preview_map").length).toBe(1);
    expect(window.AMap).toBe(undefined);
});

test("with a map configured the preview shows a read-only map at the location", async () => {
    const maps = [];
    window.AMap = {
        Map: class {
            constructor(element, options) {
                maps.push(options);
            }
            add() {}
            on() {}
        },
        Marker: class {
            setPosition() {}
            show() {}
            hide() {}
        },
    };
    try {
        await mountWithCleanup(GpsPreview, {
            props: { location: LOCATION, mapConfig: { provider: "amap", key: "demo" }, height: 160 },
        });
        await settle();
        expect(maps.length).toBe(1);
        // 只读预览: 不能拖动、缩放, 也不能打点
        expect(maps[0].dragEnable).toBe(false);
        expect(maps[0].zoomEnable).toBe(false);
    } finally {
        delete window.AMap;
    }
});

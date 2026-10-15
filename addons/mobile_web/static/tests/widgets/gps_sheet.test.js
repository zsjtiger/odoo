import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { gcj02ToWgs84, wgs84ToGcj02 } from "@web/views/fields/gps/gps_utils";
import { MobileGpsSheet } from "@mobile_web/widgets/gps_sheet/gps_sheet";

describe.current.tags("mobile");

const RESULT = { address: "北京市朝阳区建国路 88 号", latitude: 39.9042, longitude: 116.4074 };

/** 两个坐标是否在误差 eps 之内 */
function near(actual, expected, eps = 1e-5) {
    expect(Math.abs(actual - expected) < eps).toBe(true);
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

async function mountSheet(props = {}) {
    const confirmed = [];
    onRpc("gps", "search_address", () => [RESULT]);
    onRpc("gps", "reverse_address", () => ({}));
    await mountWithCleanup(MobileGpsSheet, {
        props: {
            title: "Location",
            location: null,
            mapConfig: {},
            onConfirm: (location) => confirmed.push(location),
            onClose: () => {},
            ...props,
        },
    });
    return confirmed;
}

test("without a map key the sheet shows the placeholder and the coordinate fields", async () => {
    await mountSheet({ location: { address: "A", latitude: 31.2304, longitude: 121.4737, source: "manual" } });
    await settle();
    expect(queryAll(".m_gps_map_placeholder").length).toBe(1);
    // 数字输入框的显示精度由浏览器决定, 这里比较数值
    near(Number(queryAll(".m_gps_coords input")[0].value), 31.2304, 1e-3);
    near(Number(queryAll(".m_gps_coords input")[1].value), 121.4737, 1e-3);
});

test("picking a search result fills the location and confirm returns it as a search source", async () => {
    const confirmed = await mountSheet();
    await settle();
    const input = queryOne(".m_gps_sheet .m_sheet_search_input");
    input.value = "建国路";
    input.dispatchEvent(new Event("input"));
    await new Promise((resolve) => setTimeout(resolve, 400));
    await settle();
    await click(".m_gps_results .m_sheet_item");
    await settle();
    expect(queryOne(".m_gps_form input[type=text]")).toHaveValue(RESULT.address);
    await click(".m_sheet_btn_primary");
    await settle();
    expect(confirmed).toEqual([{ ...RESULT, source: "search" }]);
});

test("confirm with an out of range latitude shows an error and returns nothing", async () => {
    const confirmed = await mountSheet({
        location: { address: "A", latitude: 95, longitude: 10, source: "manual" },
    });
    await settle();
    await click(".m_sheet_btn_primary");
    await settle();
    expect(confirmed).toEqual([]);
    expect(queryOne(".m_form_error")).toHaveText("The latitude is missing or out of range.");
});

test("locate me takes the device position as a device source", async () => {
    const confirmed = await mountSheet();
    await settle();
    const original = navigator.geolocation;
    Object.defineProperty(navigator, "geolocation", {
        configurable: true,
        value: {
            getCurrentPosition: (success) => success({ coords: { latitude: 31.2304, longitude: 121.4737 } }),
        },
    });
    try {
        await click(".m_gps_locate");
        await settle();
        await click(".m_sheet_btn_primary");
        await settle();
    } finally {
        Object.defineProperty(navigator, "geolocation", { configurable: true, value: original });
    }
    expect(confirmed).toEqual([{ address: "", latitude: 31.2304, longitude: 121.4737, source: "device" }]);
});

test("a failed device lookup shows a message", async () => {
    await mountSheet();
    await settle();
    const original = navigator.geolocation;
    Object.defineProperty(navigator, "geolocation", {
        configurable: true,
        value: { getCurrentPosition: (_success, failure) => failure() },
    });
    try {
        await click(".m_gps_locate");
        await settle();
    } finally {
        Object.defineProperty(navigator, "geolocation", { configurable: true, value: original });
    }
    expect(queryOne(".m_form_error")).toHaveText("Could not get the device location.");
});

test("with a map key a click on the map returns the point in WGS84", async () => {
    const created = { center: null, clickHandler: null };
    window.AMap = {
        Map: class {
            constructor(el, options) {
                created.center = options.center;
            }
            add() {}
            on(event, handler) {
                if (event === "click") {
                    created.clickHandler = handler;
                }
            }
            setCenter() {}
        },
        Marker: class {
            setPosition() {}
            show() {}
            hide() {}
        },
    };
    try {
        const confirmed = await mountSheet({ mapConfig: { provider: "amap", key: "demo" } });
        await settle();
        expect(queryAll(".m_gps_map_placeholder").length).toBe(0);
        const [lng, lat] = created.center;
        near(lat, wgs84ToGcj02(39.9042, 116.4074).latitude, 1e-6);
        near(lng, wgs84ToGcj02(39.9042, 116.4074).longitude, 1e-6);
        // 高德地图给出的是 GCJ-02 坐标, 保存前转换为 WGS84
        created.clickHandler({ lnglat: { getLng: () => lng, getLat: () => lat } });
        await settle();
        await click(".m_sheet_btn_primary");
        await settle();
        expect(confirmed.length).toBe(1);
        expect(confirmed[0].source).toBe("map");
        near(confirmed[0].latitude, 39.9042);
        near(confirmed[0].longitude, 116.4074);
    } finally {
        delete window.AMap;
    }
});

test("coordinates convert from WGS84 to GCJ-02 and back within a few meters", () => {
    const gcj = wgs84ToGcj02(39.9042, 116.4074);
    expect(gcj.latitude).not.toBe(39.9042);
    const wgs = gcj02ToWgs84(gcj.latitude, gcj.longitude);
    near(wgs.latitude, 39.9042);
    near(wgs.longitude, 116.4074);
});

test("outside China the conversion keeps the coordinates", () => {
    expect(wgs84ToGcj02(40.7128, -74.006)).toEqual({ latitude: 40.7128, longitude: -74.006 });
});

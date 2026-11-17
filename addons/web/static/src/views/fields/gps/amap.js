import { loadJS } from "@web/core/framework/assets";

const AMAP_SCRIPT = "https://webapi.amap.com/maps?v=2.0&key=";

/**
 * 加载高德地图 JS API (只加载一次). 失败时抛出异常, 由调用方退回到无地图的显示.
 */
export async function loadAmap(key) {
    if (!window.AMap) {
        await loadJS(`${AMAP_SCRIPT}${encodeURIComponent(key)}`);
    }
    return window.AMap;
}

import { proxy } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { loadAmap } from "@web/views/fields/gps/amap";
import { gcj02ToWgs84, invalidCoordinate, wgs84ToGcj02 } from "@web/views/fields/gps/gps_utils";

const SEARCH_DELAY = 300;
// 没有当前位置时地图的默认中心 (北京)
const DEFAULT_CENTER = { latitude: 39.9042, longitude: 116.4074 };

/**
 * 位置编辑器 (桌面端与移动端共用): 搜索地址、点击地图打点、定位到设备、由坐标查地址、校验坐标.
 *
 * 状态 (state) 是响应式的, 界面直接读取它. 地图只在配置了高德 Key 时加载;
 * 地图上的点是 GCJ-02, 写入 state 的始终是 WGS84.
 */
export class GpsEditor {
    /**
     * @param {Object} orm 服务
     * @param {Object} options
     * @param {{address?: string, latitude?: number, longitude?: number, source?: string} | null} options.location
     * @param {{provider?: string, key?: string}} options.mapConfig
     */
    constructor(orm, { location = null, mapConfig = {} } = {}) {
        this.orm = orm;
        this.mapConfig = mapConfig || {};
        this.AMap = null;
        this.map = null;
        this.marker = null;
        this.searchTimer = null;
        this.state = proxy({
            query: "",
            results: [],
            location: {
                address: location?.address || "",
                latitude: location?.latitude ?? null,
                longitude: location?.longitude ?? null,
                source: location?.source || "manual",
            },
            error: "",
            mapReady: false,
        });
    }

    /** 配置了 Key 时加载高德地图; 加载失败时保留占位, 不影响坐标与搜索 */
    async loadMap() {
        if (!this.mapConfig.key) {
            return;
        }
        try {
            this.AMap = await loadAmap(this.mapConfig.key);
        } catch {
            this.AMap = null;
        }
    }

    /**
     * 在元素上创建地图. interactive 为 false 时 (只读预览) 地图不可拖动缩放, 也不能打点.
     */
    mountMap(element, { interactive = true } = {}) {
        if (!this.AMap || !element) {
            return;
        }
        const { latitude, longitude } = this.state.location.latitude !== null ? this.state.location : DEFAULT_CENTER;
        const gcj = wgs84ToGcj02(latitude, longitude);
        const options = { zoom: 16, center: [gcj.longitude, gcj.latitude] };
        if (!interactive) {
            Object.assign(options, { dragEnable: false, zoomEnable: false, doubleClickZoom: false, scrollWheel: false });
        }
        this.map = new this.AMap.Map(element, options);
        this.marker = new this.AMap.Marker({ position: [gcj.longitude, gcj.latitude] });
        this.map.add(this.marker);
        if (interactive) {
            this.map.on("click", (ev) => this.onMapClick(ev.lnglat.getLng(), ev.lnglat.getLat()));
        }
        this.state.mapReady = true;
        if (this.state.location.latitude === null) {
            this.marker.hide();
        }
    }

    /** 更新位置 (WGS84), 同时更新地图上的标记 */
    setLocation(location, { pan = true } = {}) {
        this.state.location = { ...this.state.location, ...location };
        this.state.error = "";
        const { latitude, longitude } = this.state.location;
        if (this.map && this.marker && latitude !== null && longitude !== null) {
            const gcj = wgs84ToGcj02(latitude, longitude);
            this.marker.setPosition([gcj.longitude, gcj.latitude]);
            this.marker.show();
            if (pan) {
                this.map.setCenter([gcj.longitude, gcj.latitude]);
            }
        }
    }

    /** 输入搜索词后防抖查询候选地址 */
    onQueryChange(text, callback = () => {}) {
        this.state.query = text;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.search().then(callback), SEARCH_DELAY);
    }

    async search() {
        const query = this.state.query.trim();
        this.state.results = query ? await this.orm.call("gps", "search_address", [query]) : [];
    }

    isPicked(result) {
        const { latitude, longitude } = this.state.location;
        return result.latitude === latitude && result.longitude === longitude;
    }

    pick(result) {
        this.setLocation({ ...result, source: "search" });
        this.state.results = [];
    }

    async onMapClick(lng, lat) {
        const wgs = gcj02ToWgs84(lat, lng);
        this.setLocation({ ...wgs, source: "map" }, { pan: false });
        await this.fillAddress(wgs.latitude, wgs.longitude);
    }

    /** 设备定位 (浏览器定位, WGS84); 失败时返回 false */
    locateDevice() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) {
                this.state.error = _t("Could not get the device location.");
                resolve(false);
                return;
            }
            navigator.geolocation.getCurrentPosition(
                ({ coords }) => {
                    this.setLocation({ latitude: coords.latitude, longitude: coords.longitude, source: "device" });
                    this.fillAddress(coords.latitude, coords.longitude);
                    resolve(true);
                },
                () => {
                    this.state.error = _t("Could not get the device location.");
                    resolve(false);
                }
            );
        });
    }

    /** 由坐标查地址并回填; 找不到地址时保留原地址, 并返回 false */
    async fillAddress(latitude, longitude) {
        const result = await this.orm.call("gps", "reverse_address", [latitude, longitude]);
        if (result.address) {
            this.state.location = { ...this.state.location, address: result.address };
            return true;
        }
        return false;
    }

    /** "查找地址" 按钮: 按当前坐标查询, 找不到时给出提示 */
    async findAddress() {
        const { latitude, longitude } = this.state.location;
        if (invalidCoordinate(latitude, longitude)) {
            this.state.error = _t("Enter a valid latitude and longitude first.");
            return;
        }
        if (await this.fillAddress(latitude, longitude)) {
            this.state.error = "";
        } else {
            this.state.error = _t("No address was found for this point.");
        }
    }

    setField(name, value) {
        this.setLocation({ [name]: value, source: "manual" });
    }

    setAddress(address) {
        this.state.location = { ...this.state.location, address };
    }

    /** 保存前的校验: 返回错误信息, 合法时返回 null */
    validate() {
        const invalid = invalidCoordinate(this.state.location.latitude, this.state.location.longitude);
        if (invalid) {
            const message = _t("The %s is missing or out of range.", invalid);
            this.state.error = message;
            return message;
        }
        return null;
    }

    destroy() {
        clearTimeout(this.searchTimer);
    }
}

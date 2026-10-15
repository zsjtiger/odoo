import { Component, onMounted, onWillDestroy, onWillStart, proxy, signal, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { gcj02ToWgs84, invalidCoordinate, wgs84ToGcj02 } from "@web/views/fields/gps/gps_utils";
import { fieldTexts } from "@mobile_web/core/texts";
import { loadAmap } from "@mobile_web/widgets/gps_sheet/amap";

const SEARCH_DELAY = 300;
// 没有当前位置时地图的默认中心 (北京)
const DEFAULT_CENTER = { latitude: 39.9042, longitude: 116.4074 };

const TEXTS = {
    searchAddress: _t("Search address"),
    locateMe: _t("Locate me"),
    mapUnavailable: _t("Map is not configured. Enter the coordinates below."),
    address: _t("Address"),
    latitude: _t("Latitude"),
    longitude: _t("Longitude"),
    findAddress: _t("Find address"),
    needCoordinates: _t("Enter a valid latitude and longitude first."),
    noAddress: _t("No address was found for this point."),
    noDeviceLocation: _t("Could not get the device location."),
};

/**
 * 移动端的位置编辑页 (全屏): 上方是地图, 中间是搜索框与候选地址, 底部是取消与确认.
 * 地图由 web.gps.amap_key 配置决定: 配置后加载高德地图, 可以点击地图打点, 未配置时只使用经纬度与搜索.
 *
 * props.location: 当前位置 {address, latitude, longitude} 或 null
 * props.mapConfig: 地图配置 {provider, key} 或 {}
 * props.onConfirm(location): 确认后交回 {address, latitude, longitude, source}
 */
export class MobileGpsSheet extends Component {
    texts = { ...fieldTexts, ...TEXTS };
    static template = xml`
        <t t-name="mobile_web.MobileGpsSheet">
            <div class="m_gps_sheet" role="dialog">
                <div class="m_gps_map" t-ref="this.mapRef">
                    <div t-if="!this.state.mapReady" class="m_gps_map_placeholder">
                        <t t-esc="this.texts.mapUnavailable"/>
                    </div>
                    <button type="button" class="m_gps_locate" t-on-click="this.onLocateDevice">
                        <t t-esc="this.texts.locateMe"/>
                    </button>
                </div>
                <div class="m_gps_body">
                <div class="m_sheet_search">
                    <input type="search" class="m_input m_sheet_search_input" t-att-placeholder="this.texts.searchAddress"
                           t-att-value="this.state.query" t-on-input="this.onQueryInput"/>
                </div>
                <ul class="m_sheet_list m_gps_results">
                    <li t-foreach="this.state.results" t-as="result" t-key="result_index">
                        <button type="button" t-attf-class="m_sheet_item {{ this.isPicked(result) ? 'is_selected' : '' }}"
                                t-att-data-index="result_index" t-on-click="this.onPickResult">
                            <span class="m_sheet_item_name"><t t-esc="result.address"/></span>
                            <span t-if="this.isPicked(result)" class="m_sheet_check">✓</span>
                        </button>
                    </li>
                </ul>
                <div class="m_gps_form">
                    <label class="m_gps_label"><t t-esc="this.texts.address"/></label>
                    <input type="text" class="m_input" t-att-value="this.state.location.address" t-on-input="this.onAddressChange"/>
                    <div class="m_gps_coords">
                        <div>
                            <label class="m_gps_label"><t t-esc="this.texts.latitude"/></label>
                            <input type="number" step="0.0000001" class="m_input" t-att-value="this.state.location.latitude"
                                   t-on-input="(ev) => this.onCoordinateChange('latitude', ev)"/>
                        </div>
                        <div>
                            <label class="m_gps_label"><t t-esc="this.texts.longitude"/></label>
                            <input type="number" step="0.0000001" class="m_input" t-att-value="this.state.location.longitude"
                                   t-on-input="(ev) => this.onCoordinateChange('longitude', ev)"/>
                        </div>
                    </div>
                    <button type="button" class="m_btn m_btn_secondary m_gps_find" t-on-click="this.onReverse"><t t-esc="this.texts.findAddress"/></button>
                    <p t-if="this.state.error" class="m_form_error"><t t-esc="this.state.error"/></p>
                </div>
                </div>
                <footer class="m_gps_footer">
                    <button type="button" class="m_sheet_btn" t-on-click="this.onCancel"><t t-esc="this.texts.cancel"/></button>
                    <button type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
                </footer>
            </div>
        </t>
    `;
    props = useProps({
        title: t.string().optional(""),
        location: t.or([t.object(), t.literal(null)]).optional(null),
        mapConfig: t.object().optional({}),
        onConfirm: t.function(),
        onClose: t.function(),
    });
    orm = useService("orm");
    mapRef = signal.ref();
    state = proxy({
        query: "",
        results: [],
        location: { address: "", latitude: null, longitude: null, source: "manual" },
        error: "",
        mapReady: false,
    });
    searchTimer = null;
    map = null;
    marker = null;

    setup() {
        if (this.props.location) {
            const { address, latitude, longitude, source } = this.props.location;
            this.state.location = { address: address || "", latitude, longitude, source: source || "manual" };
        }
        onWillStart(() => this.loadMap());
        onMounted(() => this.initMap());
        onWillDestroy(() => clearTimeout(this.searchTimer));
    }

    /** 高德地图脚本只在配置了 Key 时加载; 加载失败时保留占位文字 */
    async loadMap() {
        if (this.props.mapConfig.key) {
            try {
                this.AMap = await loadAmap(this.props.mapConfig.key);
            } catch {
                this.AMap = null;
            }
        }
    }

    initMap() {
        const mapEl = this.mapRef();
        if (!this.AMap || !mapEl) {
            return;
        }
        const center = this.state.location.latitude !== null
            ? this.state.location
            : DEFAULT_CENTER;
        const gcj = wgs84ToGcj02(center.latitude, center.longitude);
        this.map = new this.AMap.Map(mapEl, { zoom: 16, center: [gcj.longitude, gcj.latitude] });
        this.marker = new this.AMap.Marker({ position: [gcj.longitude, gcj.latitude] });
        this.map.add(this.marker);
        this.map.on("click", (ev) => this.onMapClick(ev.lnglat.getLng(), ev.lnglat.getLat()));
        this.state.mapReady = true;
        if (this.state.location.latitude === null) {
            this.marker.hide();
        }
    }

    /** 把地图上的位置 (GCJ-02) 转为存储用的 WGS84, 并更新地图与表单 */
    setLocation(location, { pan = true } = {}) {
        this.state.location = { ...this.state.location, ...location };
        this.state.error = "";
        if (this.map && this.marker && location.latitude !== undefined && location.latitude !== null) {
            const gcj = wgs84ToGcj02(location.latitude, location.longitude);
            this.marker.setPosition([gcj.longitude, gcj.latitude]);
            this.marker.show();
            if (pan) {
                this.map.setCenter([gcj.longitude, gcj.latitude]);
            }
        }
    }

    async onMapClick(lng, lat) {
        const wgs = gcj02ToWgs84(lat, lng);
        this.setLocation({ ...wgs, source: "map" }, { pan: false });
        await this.fillAddress(wgs.latitude, wgs.longitude);
    }

    /** 由坐标查询地址并回填 (找不到地址时只保留坐标) */
    async fillAddress(latitude, longitude) {
        const result = await this.orm.call("gps", "reverse_address", [latitude, longitude]);
        if (result.address) {
            this.state.location = { ...this.state.location, address: result.address };
        }
    }

    onLocateDevice() {
        navigator.geolocation?.getCurrentPosition(
            (position) => {
                const { latitude, longitude } = position.coords;
                this.setLocation({ latitude, longitude, source: "device" });
                this.fillAddress(latitude, longitude);
            },
            () => {
                this.state.error = this.texts.noDeviceLocation;
            }
        );
    }

    onQueryInput(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.search(), SEARCH_DELAY);
    }

    async search() {
        const query = this.state.query.trim();
        this.state.results = query ? await this.orm.call("gps", "search_address", [query]) : [];
    }

    isPicked(result) {
        const { latitude, longitude } = this.state.location;
        return result.latitude === latitude && result.longitude === longitude;
    }

    onPickResult(ev) {
        const result = this.state.results[Number(ev.currentTarget.dataset.index)];
        if (result) {
            this.setLocation({ ...result, source: "search" });
        }
    }

    onAddressChange(ev) {
        this.state.location = { ...this.state.location, address: ev.target.value };
    }

    onCoordinateChange(name, ev) {
        const value = ev.target.value === "" ? null : Number(ev.target.value);
        this.setLocation({ [name]: value, source: "manual" });
    }

    async onReverse() {
        const { latitude, longitude } = this.state.location;
        if (invalidCoordinate(latitude, longitude)) {
            this.state.error = this.texts.needCoordinates;
            return;
        }
        const result = await this.orm.call("gps", "reverse_address", [latitude, longitude]);
        if (result.address) {
            this.state.location = { ...this.state.location, address: result.address };
            this.state.error = "";
        } else {
            this.state.error = this.texts.noAddress;
        }
    }

    onConfirm() {
        const invalid = invalidCoordinate(this.state.location.latitude, this.state.location.longitude);
        if (invalid) {
            this.state.error = _t("The %s is missing or out of range.", invalid);
            return;
        }
        this.props.onConfirm({ ...this.state.location });
    }

    onCancel() {
        this.props.onClose();
    }
}

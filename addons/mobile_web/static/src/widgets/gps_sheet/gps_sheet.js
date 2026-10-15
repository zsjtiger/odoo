import { Component, onMounted, onWillDestroy, onWillStart, signal, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { GpsEditor } from "@web/views/fields/gps/gps_editor";
import { fieldTexts } from "@mobile_web/core/texts";

const TEXTS = {
    searchAddress: _t("Search address"),
    locateMe: _t("Locate me"),
    mapUnavailable: _t("Map is not configured. Enter the coordinates below."),
    address: _t("Address"),
    latitude: _t("Latitude"),
    longitude: _t("Longitude"),
    findAddress: _t("Find address"),
};

/**
 * 移动端的位置编辑页 (全屏): 上方是地图, 中间是搜索框与候选地址, 底部是取消与确认.
 * 逻辑在 GpsEditor 中 (与桌面端共用), 这里只负责布局与交互.
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
                    <div t-if="!this.editor.state.mapReady" class="m_gps_map_placeholder">
                        <t t-esc="this.texts.mapUnavailable"/>
                    </div>
                    <button type="button" class="m_gps_locate" t-on-click="this.onLocateDevice">
                        <t t-esc="this.texts.locateMe"/>
                    </button>
                </div>
                <div class="m_gps_body">
                    <div class="m_sheet_search">
                        <input type="search" class="m_input m_sheet_search_input" t-att-placeholder="this.texts.searchAddress"
                               t-att-value="this.editor.state.query" t-on-input="this.onQueryInput"/>
                    </div>
                    <ul class="m_sheet_list m_gps_results">
                        <li t-foreach="this.editor.state.results" t-as="result" t-key="result_index">
                            <button type="button" t-attf-class="m_sheet_item {{ this.editor.isPicked(result) ? 'is_selected' : '' }}"
                                    t-att-data-index="result_index" t-on-click="this.onPickResult">
                                <span class="m_sheet_item_name"><t t-esc="result.address"/></span>
                                <span t-if="this.editor.isPicked(result)" class="m_sheet_check">✓</span>
                            </button>
                        </li>
                    </ul>
                    <div class="m_gps_form">
                        <label class="m_gps_label"><t t-esc="this.texts.address"/></label>
                        <input type="text" class="m_input" t-att-value="this.editor.state.location.address" t-on-input="this.onAddressChange"/>
                        <div class="m_gps_coords">
                            <div>
                                <label class="m_gps_label"><t t-esc="this.texts.latitude"/></label>
                                <input type="number" step="0.0000001" class="m_input" t-att-value="this.editor.state.location.latitude"
                                       t-on-input="(ev) => this.onCoordinateChange('latitude', ev)"/>
                            </div>
                            <div>
                                <label class="m_gps_label"><t t-esc="this.texts.longitude"/></label>
                                <input type="number" step="0.0000001" class="m_input" t-att-value="this.editor.state.location.longitude"
                                       t-on-input="(ev) => this.onCoordinateChange('longitude', ev)"/>
                            </div>
                        </div>
                        <button type="button" class="m_btn m_btn_secondary m_gps_find" t-on-click="this.onFindAddress"><t t-esc="this.texts.findAddress"/></button>
                        <p t-if="this.editor.state.error" class="m_form_error"><t t-esc="this.editor.state.error"/></p>
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

    setup() {
        this.editor = new GpsEditor(this.orm, { location: this.props.location, mapConfig: this.props.mapConfig });
        onWillStart(() => this.editor.loadMap());
        onMounted(() => this.editor.mountMap(this.mapRef()));
        onWillDestroy(() => this.editor.destroy());
    }

    onQueryInput(ev) {
        this.editor.onQueryChange(ev.target.value);
    }

    onPickResult(ev) {
        const result = this.editor.state.results[Number(ev.currentTarget.dataset.index)];
        if (result) {
            this.editor.pick(result);
        }
    }

    onAddressChange(ev) {
        this.editor.setAddress(ev.target.value);
    }

    onCoordinateChange(name, ev) {
        this.editor.setField(name, ev.target.value === "" ? null : Number(ev.target.value));
    }

    onLocateDevice() {
        this.editor.locateDevice();
    }

    onFindAddress() {
        this.editor.findAddress();
    }

    onConfirm() {
        if (!this.editor.validate()) {
            this.props.onConfirm({ ...this.editor.state.location });
        }
    }

    onCancel() {
        this.props.onClose();
    }
}

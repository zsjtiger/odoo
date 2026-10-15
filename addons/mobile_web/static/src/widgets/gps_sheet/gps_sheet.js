import { Component, onWillDestroy, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { invalidCoordinate } from "@web/views/fields/gps/gps_utils";
import { fieldTexts } from "@mobile_web/core/texts";

const SEARCH_DELAY = 300;

const TEXTS = {
    searchAddress: _t("Search address"),
    address: _t("Address"),
    latitude: _t("Latitude"),
    longitude: _t("Longitude"),
    findAddress: _t("Find address"),
    needCoordinates: _t("Enter a valid latitude and longitude first."),
    noAddress: _t("No address was found for this point."),
};

/**
 * 移动端的位置编辑弹层: 搜索地址、填写或修改经纬度与地址, 确认后交回位置.
 *
 * props.location: 当前位置 {id, address, latitude, longitude} 或 null
 * props.onConfirm(location): 确认后交回 {address, latitude, longitude, source}
 */
export class MobileGpsSheet extends Component {
    texts = { ...fieldTexts, ...TEXTS };
    static template = xml`
        <t t-name="mobile_web.MobileGpsSheet">
            <div class="m_sheet_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_sheet m_gps_sheet" role="dialog">
                    <header class="m_sheet_header">
                        <button type="button" class="m_sheet_btn" t-on-click="this.onCancel"><t t-esc="this.texts.cancel"/></button>
                        <span class="m_sheet_title"><t t-esc="this.props.title"/></span>
                        <button type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
                    </header>
                    <div class="m_sheet_search">
                        <input type="search" class="m_input m_sheet_search_input" t-att-placeholder="this.texts.searchAddress"
                               t-att-value="this.state.query" t-on-input="this.onQueryInput"/>
                    </div>
                    <ul t-if="this.state.results.length" class="m_sheet_list">
                        <li t-foreach="this.state.results" t-as="result" t-key="result_index">
                            <button type="button" class="m_sheet_item" t-att-data-index="result_index" t-on-click="this.onPickResult">
                                <span class="m_sheet_item_name"><t t-esc="result.address"/></span>
                            </button>
                        </li>
                    </ul>
                    <div class="m_gps_form">
                        <label class="m_gps_label"><t t-esc="this.texts.address"/></label>
                        <input type="text" class="m_input" t-att-value="this.state.location.address" t-on-input="this.onAddressChange"/>
                        <label class="m_gps_label"><t t-esc="this.texts.latitude"/></label>
                        <input type="number" step="0.0000001" class="m_input" t-att-value="this.state.location.latitude"
                               t-on-input="(ev) => this.onCoordinateChange('latitude', ev)"/>
                        <label class="m_gps_label"><t t-esc="this.texts.longitude"/></label>
                        <input type="number" step="0.0000001" class="m_input" t-att-value="this.state.location.longitude"
                               t-on-input="(ev) => this.onCoordinateChange('longitude', ev)"/>
                        <button type="button" class="m_btn m_btn_secondary m_gps_find" t-on-click="this.onReverse"><t t-esc="this.texts.findAddress"/></button>
                        <p t-if="this.state.error" class="m_form_error"><t t-esc="this.state.error"/></p>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        title: t.string().optional(""),
        location: t.or([t.object(), t.literal(null)]).optional(null),
        onConfirm: t.function(),
        onClose: t.function(),
    });
    orm = useService("orm");
    state = proxy({
        query: "",
        results: [],
        location: { address: "", latitude: null, longitude: null, source: "manual" },
        error: "",
    });
    searchTimer = null;

    setup() {
        if (this.props.location) {
            const { address, latitude, longitude, source } = this.props.location;
            this.state.location = { address: address || "", latitude, longitude, source: source || "manual" };
        }
        onWillDestroy(() => clearTimeout(this.searchTimer));
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

    onPickResult(ev) {
        const result = this.state.results[Number(ev.currentTarget.dataset.index)];
        if (result) {
            this.state.location = { ...result, source: "search" };
            this.state.results = [];
            this.state.error = "";
        }
    }

    onAddressChange(ev) {
        this.state.location = { ...this.state.location, address: ev.target.value };
    }

    onCoordinateChange(name, ev) {
        const value = ev.target.value === "" ? null : Number(ev.target.value);
        this.state.location = { ...this.state.location, [name]: value, source: "manual" };
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

    onBackdropClick(ev) {
        if (ev.target.classList.contains("m_sheet_backdrop")) {
            this.props.onClose();
        }
    }
}

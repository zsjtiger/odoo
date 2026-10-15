import { Component, onWillDestroy, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { invalidCoordinate, saveLocation } from "@web/views/fields/gps/gps_utils";

const SEARCH_DELAY = 300;

const TEXTS = {
    searchAddress: _t("Search address"),
    address: _t("Address"),
    latitude: _t("Latitude"),
    longitude: _t("Longitude"),
    cancel: _t("Cancel"),
    findAddress: _t("Find address"),
    confirm: _t("Confirm"),
    selectLocation: _t("Select location…"),
    needCoordinates: _t("Enter a valid latitude and longitude first."),
    noAddress: _t("No address was found for this point."),
};

/**
 * 位置编辑对话框: 搜索地址、填写或修改经纬度与地址, 确认后保存为 gps 记录.
 *
 * props.value: 当前位置 {id, display_name} 或 false
 * props.owner: 所属记录 {model, field, resId}
 */
export class GpsDialog extends Component {
    static components = { Dialog };
    texts = TEXTS;
    static template = xml`
        <Dialog title="this.props.title" size="'md'">
            <div class="mb-2">
                <input type="search" class="form-control" t-att-placeholder="this.texts.searchAddress" t-att-value="this.state.query"
                       t-on-input="this.onQueryInput"/>
            </div>
            <div t-if="this.state.results.length" class="list-group mb-3">
                <t t-foreach="this.state.results" t-as="result" t-key="result_index">
                    <button type="button" class="list-group-item list-group-item-action text-start" t-on-click="() => this.onPickResult(result)">
                        <t t-esc="result.address"/>
                    </button>
                </t>
            </div>
            <div class="mb-2">
                <label class="form-label"><t t-esc="this.texts.address"/></label>
                <input type="text" class="form-control" t-att-value="this.state.location.address"
                       t-on-input="this.onAddressChange"/>
            </div>
            <div class="row g-2 mb-2">
                <div class="col">
                    <label class="form-label"><t t-esc="this.texts.latitude"/></label>
                    <input type="number" step="0.0000001" class="form-control" t-att-value="this.state.location.latitude"
                           t-on-input="(ev) => this.onCoordinateChange('latitude', ev)"/>
                </div>
                <div class="col">
                    <label class="form-label"><t t-esc="this.texts.longitude"/></label>
                    <input type="number" step="0.0000001" class="form-control" t-att-value="this.state.location.longitude"
                           t-on-input="(ev) => this.onCoordinateChange('longitude', ev)"/>
                </div>
            </div>
            <div t-if="this.state.error" class="text-danger small mb-2"><t t-esc="this.state.error"/></div>
            <t t-set-slot="footer">
                <button type="button" class="btn btn-secondary" t-on-click="() => this.props.close()"><t t-esc="this.texts.cancel"/></button>
                <button type="button" class="btn btn-secondary" t-on-click="this.onReverse"><t t-esc="this.texts.findAddress"/></button>
                <button type="button" class="btn btn-primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
            </t>
        </Dialog>
    `;

    props = useProps({
        title: t.string().optional(""),
        value: t.or([t.object(), t.literal(false)]).optional(false),
        owner: t.object(),
        onConfirm: t.function(),
        close: t.function(),
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
        // 打开时, 有已保存的位置则先读取它的经纬度
        if (this.props.value) {
            this.loadCurrent();
        }
        onWillDestroy(() => clearTimeout(this.searchTimer));
    }

    async loadCurrent() {
        const [gps] = await this.orm.read("gps", [this.props.value.id], ["address", "latitude", "longitude", "source"]);
        this.state.location = {
            address: gps.address || "",
            latitude: gps.latitude,
            longitude: gps.longitude,
            source: gps.source || "manual",
        };
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

    onPickResult(result) {
        this.state.location = { ...result, source: "search" };
        this.state.results = [];
        this.state.error = "";
    }

    onAddressChange(ev) {
        this.state.location = { ...this.state.location, address: ev.target.value };
    }

    onCoordinateChange(name, ev) {
        const value = ev.target.value === "" ? null : Number(ev.target.value);
        this.state.location = { ...this.state.location, [name]: value, source: "manual" };
    }

    /** 由坐标查询地址 (地址为空时填入, 不覆盖用户已填写的地址) */
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

    async onConfirm() {
        const { latitude, longitude } = this.state.location;
        const invalid = invalidCoordinate(latitude, longitude);
        if (invalid) {
            this.state.error = _t("The %s is missing or out of range.", invalid);
            return;
        }
        const value = await saveLocation(this.orm, {
            value: this.props.value,
            location: this.state.location,
            owner: this.props.owner,
        });
        this.props.onConfirm(value);
        this.props.close();
    }
}

/**
 * 位置控件 (many2one 指向 gps 模型, widget="gps"): 显示地址, 点击打开位置编辑对话框
 */
export class GpsField extends Component {
    texts = TEXTS;
    static template = xml`
        <button type="button" class="o_input o_gps_field text-start w-100" t-att-id="this.props.id"
                t-att-disabled="this.props.readonly" t-on-click="this.openDialog">
            <t t-if="this.displayName"><t t-esc="this.displayName"/></t>
            <span t-else="" class="text-muted"><t t-esc="this.texts.selectLocation"/></span>
        </button>
    `;
    props = useProps(standardFieldProps);
    dialog = useService("dialog");

    get value() {
        return this.props.record.data[this.props.name] || false;
    }

    get displayName() {
        return this.value ? this.value.display_name : "";
    }

    openDialog() {
        const field = this.props.record.fields[this.props.name];
        this.dialog.add(GpsDialog, {
            title: field.string,
            value: this.value,
            owner: { model: this.props.record.resModel, field: this.props.name, resId: this.props.record.resId },
            onConfirm: (value) => this.props.record.update({ [this.props.name]: value }),
        });
    }
}

registry.category("fields").add("gps", {
    component: GpsField,
    supportedTypes: ["many2one"],
});

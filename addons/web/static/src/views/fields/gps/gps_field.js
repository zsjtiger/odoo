import { Component, onMounted, onWillDestroy, onWillStart, onWillUpdateProps, proxy, signal, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { GpsEditor } from "@web/views/fields/gps/gps_editor";
import { saveLocation } from "@web/views/fields/gps/gps_utils";
import { GpsPreview, readLocation } from "@web/views/fields/gps/gps_preview";

const TEXTS = {
    searchAddress: _t("Search address"),
    locateMe: _t("Locate me"),
    mapUnavailable: _t("Map is not configured. Enter the coordinates below."),
    address: _t("Address"),
    latitude: _t("Latitude"),
    longitude: _t("Longitude"),
    cancel: _t("Cancel"),
    findAddress: _t("Find address"),
    confirm: _t("Confirm"),
    selectLocation: _t("Get location"),
};

/**
 * 位置编辑对话框 (桌面端): 左侧地图, 右侧搜索、候选地址与地址、经纬度.
 * 与移动端的全屏位置页布局对应; 逻辑在 GpsEditor 中共用.
 *
 * props.value: 当前位置 {id, display_name} 或 false
 * props.owner: 所属记录 {model, field, resId}
 * props.mapConfig: 地图配置 {provider, key} 或 {}
 */
export class GpsDialog extends Component {
    static components = { Dialog };
    static template = xml`
        <Dialog title="this.props.title" size="'xl'">
            <div class="row g-3">
                <div class="col-lg-6">
                    <div class="o_gps_map position-relative w-100 rounded bg-light" t-ref="this.mapRef" style="height: 420px;">
                        <div t-if="!this.editor.state.mapReady" class="o_gps_map_placeholder position-absolute top-50 start-50 translate-middle text-center text-muted px-3">
                            <t t-esc="this.texts.mapUnavailable"/>
                        </div>
                        <button type="button" class="btn btn-secondary btn-sm position-absolute bottom-0 end-0 m-2" t-on-click="this.onLocateDevice">
                            <t t-esc="this.texts.locateMe"/>
                        </button>
                    </div>
                </div>
                <div class="col-lg-6">
                    <input type="search" class="form-control mb-2" t-att-placeholder="this.texts.searchAddress"
                           t-att-value="this.editor.state.query" t-on-input="this.onQueryInput"/>
                    <div t-if="this.editor.state.results.length" class="list-group mb-3" style="max-height: 180px; overflow-y: auto;">
                        <t t-foreach="this.editor.state.results" t-as="result" t-key="result_index">
                            <button type="button" t-attf-class="list-group-item list-group-item-action text-start d-flex justify-content-between {{ this.editor.isPicked(result) ? 'active' : '' }}"
                                    t-on-click="() => this.editor.pick(result)">
                                <span t-esc="result.address"/>
                                <span t-if="this.editor.isPicked(result)">✓</span>
                            </button>
                        </t>
                    </div>
                    <div class="mb-2">
                        <label class="form-label"><t t-esc="this.texts.address"/></label>
                        <input type="text" class="form-control" t-att-value="this.editor.state.location.address" t-on-input="this.onAddressChange"/>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col">
                            <label class="form-label"><t t-esc="this.texts.latitude"/></label>
                            <input type="number" step="0.0000001" class="form-control" t-att-value="this.editor.state.location.latitude"
                                   t-on-input="(ev) => this.onCoordinateChange('latitude', ev)"/>
                        </div>
                        <div class="col">
                            <label class="form-label"><t t-esc="this.texts.longitude"/></label>
                            <input type="number" step="0.0000001" class="form-control" t-att-value="this.editor.state.location.longitude"
                                   t-on-input="(ev) => this.onCoordinateChange('longitude', ev)"/>
                        </div>
                    </div>
                    <button type="button" class="btn btn-secondary mb-2" t-on-click="this.onFindAddress"><t t-esc="this.texts.findAddress"/></button>
                    <div t-if="this.editor.state.error" class="text-danger small"><t t-esc="this.editor.state.error"/></div>
                </div>
            </div>
            <t t-set-slot="footer">
                <button type="button" class="btn btn-secondary" t-on-click="() => this.props.close()"><t t-esc="this.texts.cancel"/></button>
                <button type="button" class="btn btn-primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
            </t>
        </Dialog>
    `;

    props = useProps({
        title: t.string().optional(""),
        value: t.or([t.object(), t.literal(false)]).optional(false),
        owner: t.object(),
        mapConfig: t.object().optional({}),
        onConfirm: t.function(),
        close: t.function(),
    });
    orm = useService("orm");
    texts = TEXTS;
    mapRef = signal.ref();

    setup() {
        onWillStart(async () => {
            let location = null;
            if (this.props.value) {
                const [gps] = await this.orm.read("gps", [this.props.value.id], ["address", "latitude", "longitude", "source"]);
                location = gps;
            }
            this.editor = new GpsEditor(this.orm, { location, mapConfig: this.props.mapConfig });
            await this.editor.loadMap();
        });
        onMounted(() => this.editor.mountMap(this.mapRef()));
        onWillDestroy(() => this.editor?.destroy());
    }

    onQueryInput(ev) {
        this.editor.onQueryChange(ev.target.value);
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

    async onConfirm() {
        if (this.editor.validate()) {
            return;
        }
        const value = await saveLocation(this.orm, {
            value: this.props.value,
            location: this.editor.state.location,
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
    static components = { GpsPreview };
    static template = xml`
        <div t-if="this.props.readonly" class="o_gps_field_readonly">
            <div t-if="this.displayName"><t t-esc="this.displayName"/></div>
            <t t-foreach="this.previewList" t-as="preview" t-key="preview.key">
                <GpsPreview location="preview.location" mapConfig="this.mapConfig" height="240"/>
            </t>
        </div>
        <button t-else="" type="button" class="o_input o_gps_field text-start w-100" t-att-id="this.props.id" t-on-click="this.openDialog">
            <t t-if="this.displayName"><t t-esc="this.displayName"/></t>
            <span t-else="" class="text-muted"><t t-esc="this.texts.selectLocation"/></span>
        </button>
    `;
    props = useProps(standardFieldProps);
    dialog = useService("dialog");
    orm = useService("orm");
    texts = TEXTS;
    mapConfig = {};

    state = proxy({ location: null });

    setup() {
        // 地图配置(高德 Key)在控件创建时读取一次
        onWillStart(async () => {
            this.mapConfig = (await this.orm.call("gps", "get_map_config", [])) || {};
            await this.loadLocation(this.props);
        });
        // 值变化后 (保存或放弃改动), 重新读取位置用于只读预览
        onWillUpdateProps((nextProps) => this.loadLocation(nextProps));
    }

    /** 只读预览使用的位置 (带 key, 位置变化时预览重新创建) */
    get previewList() {
        const location = this.state.location;
        if (!location || !this.value) {
            return [];
        }
        return [{ key: `${this.value.id}:${location.latitude}:${location.longitude}`, location }];
    }

    async loadLocation(props) {
        const value = props.record.data[props.name];
        this.state.location = value ? await readLocation(this.orm, value.id) : null;
    }

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
            mapConfig: this.mapConfig,
            owner: { model: this.props.record.resModel, field: this.props.name, resId: this.props.record.resId },
            onConfirm: (value) => this.props.record.update({ [this.props.name]: value }),
        });
    }
}

registry.category("fields").add("gps", {
    component: GpsField,
    supportedTypes: ["many2one"],
});

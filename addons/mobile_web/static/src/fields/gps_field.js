import { Component, onWillStart, onWillUpdateProps, proxy, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { saveLocation } from "@web/views/fields/gps/gps_utils";
import { GpsPreview, readLocation } from "@web/views/fields/gps/gps_preview";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { MobileGpsSheet } from "@mobile_web/widgets/gps_sheet/gps_sheet";
import { PickerButton } from "@mobile_web/widgets/picker/picker";
import { fieldTexts } from "@mobile_web/core/texts";
import { _t } from "@web/core/data/l10n/translation";

/** many2one 的值为 [id, 地址] */
function pairName(pair) {
    return pair && (pair[1] ?? `#${pair[0]}`);
}

/**
 * 位置控件 (many2one 指向 gps 模型, widget="gps"): 显示地址, 点击打开位置编辑弹层.
 * 确认后保存为 gps 记录 (新建或更新) 并写回 many2one 的值.
 */
export class GpsField extends Component {
    texts = { ...fieldTexts, getLocation: _t("Get location") };
    static components = { MobileGpsSheet, PickerButton, GpsPreview };
    static template = xml`
        <t t-name="mobile_web.GpsField">
            <t t-if="this.props.readonly">
                <span class="m_field_value"><t t-esc="this.displayName"/></span>
                <t t-foreach="this.previewList" t-as="preview" t-key="preview.key">
                    <GpsPreview location="preview.location" mapConfig="this.mapConfig" height="160"/>
                </t>
            </t>
            <t t-else="">
                <PickerButton value="this.current ? this.displayName : false" placeholder="this.texts.getLocation" onClick="this.openSheet"/>
                <MobileGpsSheet t-if="this.state.open" title="this.props.field.string" location="this.currentLocation"
                    mapConfig="this.mapConfig" onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false, location: null });
    mapConfig = {};

    setup() {
        // 地图配置(高德 Key)在控件创建时读取一次
        onWillStart(async () => {
            this.mapConfig = (await this.orm.call("gps", "get_map_config", [])) || {};
            await this.loadLocation(this.props);
        });
        // 值变化后 (保存或放弃改动), 重新读取位置用于只读预览
        onWillUpdateProps((nextProps) => this.loadLocation(nextProps));
    }

    get current() {
        return this.props.record.data[this.props.name] || false;
    }
    get displayName() {
        return displayOrEmpty(pairName(this.current));
    }
    /** 只读预览使用的位置 (带 key, 位置变化时预览重新创建) */
    get previewList() {
        const location = this.state.location;
        if (!location || !this.current) {
            return [];
        }
        return [{ key: `${this.current[0]}:${location.latitude}:${location.longitude}`, location }];
    }

    async loadLocation(props) {
        const value = props.record.data[props.name];
        this.state.location = value ? await readLocation(this.orm, value[0]) : null;
    }

    get currentLocation() {
        // 已保存的位置在打开弹层时读取经纬度
        return this.current ? this.loadedLocation : null;
    }
    openSheet = async () => {
        this.loadedLocation = null;
        if (this.current) {
            const [gps] = await this.orm.read("gps", [this.current[0]], ["address", "latitude", "longitude", "source"]);
            this.loadedLocation = { id: gps.id, ...gps };
        }
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = async (location) => {
        const value = await saveLocation(this.orm, {
            value: this.current ? { id: this.current[0], display_name: pairName(this.current) } : false,
            location,
            owner: { model: this.props.resModel, field: this.props.name, resId: this.props.record.resId },
        });
        this.props.onChange([value.id, value.display_name]);
        this.close();
    };
}
mobileFieldRegistry.add("gps", GpsField);

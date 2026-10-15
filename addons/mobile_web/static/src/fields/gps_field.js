import { Component, proxy, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { saveLocation } from "@web/views/fields/gps/gps_utils";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { MobileGpsSheet } from "@mobile_web/widgets/gps_sheet/gps_sheet";
import { PickerButton } from "@mobile_web/widgets/picker/picker";
import { fieldTexts } from "@mobile_web/core/texts";

/** many2one 的值为 [id, 地址] */
function pairName(pair) {
    return pair && (pair[1] ?? `#${pair[0]}`);
}

/**
 * 位置控件 (many2one 指向 gps 模型, widget="gps"): 显示地址, 点击打开位置编辑弹层.
 * 确认后保存为 gps 记录 (新建或更新) 并写回 many2one 的值.
 */
export class GpsField extends Component {
    texts = fieldTexts;
    static components = { MobileGpsSheet, PickerButton };
    static template = xml`
        <t t-name="mobile_web.GpsField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayName"/></span>
            <t t-else="">
                <PickerButton value="this.current ? this.displayName : false" placeholder="this.texts.select" onClick="this.openSheet"/>
                <MobileGpsSheet t-if="this.state.open" title="this.props.field.string" location="this.currentLocation"
                    onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false });

    get current() {
        return this.props.record.data[this.props.name] || false;
    }
    get displayName() {
        return displayOrEmpty(pairName(this.current));
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

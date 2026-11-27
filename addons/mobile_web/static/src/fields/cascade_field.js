import { Component, proxy, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { MobileCascadeSheet } from "@mobile_web/widgets/cascade_sheet/cascade_sheet";
import { PickerButton } from "@mobile_web/widgets/picker/picker";
import { fieldTexts } from "@mobile_web/core/texts";

/** many2one 的值为 [id, 完整路径名称] */
function pairName(pair) {
    return pair && (pair[1] ?? `#${pair[0]}`);
}

/**
 * 级联选择 (many2one, widget="cascade"): 关联模型为层级结构(parent_id)时, 按层级逐级选择.
 * 显示值为关联记录的显示名称(完整路径).
 */
export class CascadeField extends Component {
    texts = fieldTexts;
    static components = { MobileCascadeSheet, PickerButton };
    static template = xml`
        <t t-name="mobile_web.CascadeField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayName"/></span>
            <t t-else="">
                <PickerButton value="this.current ? this.displayName : false" placeholder="this.texts.select" onClick="this.openSheet"/>
                <MobileCascadeSheet t-if="this.state.open" title="this.props.field.string"
                    relation="this.props.field.relation" selected="this.currentItems"
                    onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    state = proxy({ open: false });

    get current() {
        return this.props.record.data[this.props.name] || false;
    }
    get displayName() {
        return displayOrEmpty(pairName(this.current));
    }
    get currentItems() {
        return this.current ? [{ id: this.current[0], name: pairName(this.current) }] : [];
    }
    openSheet = () => {
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        const item = selected[0];
        this.props.onChange(item ? [item.id, item.name] : false);
        this.close();
    };
}
mobileFieldRegistry.add("cascade", CascadeField);

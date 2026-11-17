import { Component, t, useProps, xml } from "@odoo/owl";

/**
 * 按钮控件: 紧凑样式与危险操作样式, 可选右侧箭头
 */
export class Button extends Component {
    static template = xml`
        <t t-name="mobile_web.Button">
            <button type="button" t-attf-class="m_button m_picker_button {{ this.props.compact ? 'm_picker_button_compact' : '' }} {{ this.props.danger ? 'm_button_danger' : '' }}"
                    t-on-click="this.onClick">
                <t t-esc="this.props.label"/>
                <span t-if="this.props.caret" class="m_picker_caret">›</span>
            </button>
        </t>
    `;
    props = useProps({
        label: t.string(),
        compact: t.boolean().optional(false),
        danger: t.boolean().optional(false),
        caret: t.boolean().optional(false),
        onClick: t.function(),
    });

    onClick() {
        this.props.onClick();
    }
}

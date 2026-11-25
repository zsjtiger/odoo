import { Component, t, useProps, xml } from "@odoo/owl";

/**
 * 按钮控件: 紧凑样式与危险操作样式, 可选右侧箭头
 */
export class Button extends Component {
    static template = xml`
        <t t-name="mobile_web.Button">
            <button type="button"
                    t-attf-class="m_button m_picker_button {{ this.props.icon ? 'm_button_icon' : (this.props.compact ? 'm_picker_button_compact' : '') }} {{ this.props.danger ? 'm_button_danger' : '' }}"
                    t-att-aria-label="this.props.icon ? this.props.label : undefined"
                    t-att-title="this.props.icon ? this.props.label : undefined"
                    t-on-click="this.onClick">
                <t t-if="this.props.icon">
                    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                        <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" fill="currentColor"/>
                    </svg>
                </t>
                <t t-else="">
                    <t t-esc="this.props.label"/>
                    <span t-if="this.props.caret" class="m_button_caret" aria-hidden="true">
                        <svg viewBox="0 0 16 16" width="12" height="12">
                            <path d="M3.5 6 8 10.5 12.5 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </span>
                </t>
            </button>
        </t>
    `;
    props = useProps({
        label: t.string(),
        compact: t.boolean().optional(false),
        danger: t.boolean().optional(false),
        caret: t.boolean().optional(false),
        icon: t.boolean().optional(false),
        onClick: t.function(),
    });

    onClick() {
        this.props.onClick();
    }
}

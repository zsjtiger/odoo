import { Component, t, useProps, xml } from "@odoo/owl";

/**
 * 开关: 复选框的移动端外观, 状态变化时回传新的布尔值
 */
export class Switch extends Component {
    static template = xml`
        <t t-name="mobile_web.Switch">
            <label class="m_switch">
                <input type="checkbox" t-att-checked="this.props.checked" t-on-change="this.onChange"/>
                <span class="m_switch_track"></span>
                <span class="m_switch_label"><t t-esc="this.props.label"/></span>
            </label>
        </t>
    `;
    props = useProps({
        checked: t.boolean().optional(false),
        label: t.string().optional(""),
        onChange: t.function(),
    });

    onChange(ev) {
        this.props.onChange(ev.target.checked);
    }
}

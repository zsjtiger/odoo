import { Component, t, useProps, xml } from "@odoo/owl";

/**
 * 选择器按钮: 显示当前值, 没有值时显示占位文字; 点击后由调用方打开弹层
 */
export class PickerButton extends Component {
    static template = xml`
        <t t-name="mobile_web.PickerButton">
            <button type="button" class="m_picker_button" t-on-click="this.onClick">
                <span t-if="this.props.value" class="m_picker_value"><t t-esc="this.props.value"/></span>
                <span t-else="" class="m_picker_placeholder"><t t-esc="this.props.placeholder"/></span>
                <span class="m_picker_caret">›</span>
            </button>
        </t>
    `;
    props = useProps({
        value: t.or([t.string(), t.literal(false)]).optional(false),
        placeholder: t.string().optional(""),
        onClick: t.function(),
    });

    onClick() {
        this.props.onClick();
    }
}

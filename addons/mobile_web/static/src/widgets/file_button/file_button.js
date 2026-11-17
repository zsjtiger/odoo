import { Component, signal, t, useProps, xml } from "@odoo/owl";

/**
 * 文件选择按钮: 点击后打开系统的文件/相机选择, 选中后以 base64 回传内容
 */
export class FileButton extends Component {
    static template = xml`
        <t t-name="mobile_web.FileButton">
            <button type="button" class="m_picker_button m_picker_button_compact" t-on-click="this.onClick">
                <t t-esc="this.props.label"/>
            </button>
            <input t-ref="this.input" type="file" class="m_visually_hidden" t-att-accept="this.props.accept"
                   t-att-capture="this.props.capture or null" t-on-change="this.onChange"/>
        </t>
    `;
    props = useProps({
        label: t.string(),
        accept: t.string().optional("image/*"),
        capture: t.string().optional(""),
        onFile: t.function(),
    });
    input = signal.ref();

    onClick() {
        this.input()?.click();
    }

    onChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            // data:<mime>;base64,<payload>
            this.props.onFile(String(reader.result).split(",")[1]);
        };
        reader.readAsDataURL(file);
    }
}

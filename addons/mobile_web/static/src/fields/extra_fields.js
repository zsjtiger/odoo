import { Component, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { NumberField, SelectionField } from "@mobile_web/fields/basic_fields";
import { fieldTexts } from "@mobile_web/core/texts";

// -----------------------------------------------------------------------------
// badge: 只读时显示为标签; 选择类与多对一字段显示其名称
// -----------------------------------------------------------------------------

export class BadgeField extends Component {
    static template = xml`
        <t t-name="mobile_web.BadgeField">
            <span class="m_badge"><t t-esc="this.label"/></span>
        </t>
    `;
    props = useProps(fieldProps);

    get label() {
        const value = this.props.record.data[this.props.name];
        if (Array.isArray(value)) {
            return displayOrEmpty(value[1]);
        }
        const option = (this.props.field.selection || []).find((o) => o[0] === value);
        return option ? option[1] : displayOrEmpty(value);
    }
}
mobileFieldRegistry.add("badge", BadgeField);

// -----------------------------------------------------------------------------
// label_selection / state_selection: 只读时显示为标签, 可编辑时与 selection 相同
// -----------------------------------------------------------------------------

export class LabelSelectionField extends Component {
    static components = { BadgeField, SelectionField };
    static template = xml`
        <t t-name="mobile_web.LabelSelectionField">
            <BadgeField t-if="this.props.readonly" t-props="this.props"/>
            <SelectionField t-else="" t-props="this.props"/>
        </t>
    `;
    props = useProps(fieldProps);
}
mobileFieldRegistry.add("label_selection", LabelSelectionField);
mobileFieldRegistry.add("state_selection", LabelSelectionField);

// -----------------------------------------------------------------------------
// password: 只读时显示遮罩, 编辑时使用密码输入框; 值不会显示在界面上
// -----------------------------------------------------------------------------

export class PasswordField extends Component {
    static template = xml`
        <t t-name="mobile_web.PasswordField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.mask"/></span>
            <input t-else="" type="password" class="m_input" autocomplete="new-password" enterkeyhint="done"
                   t-att-placeholder="this.props.attrs.placeholder or ''" t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get mask() {
        return this.props.record.data[this.props.name] ? "••••••" : "";
    }
    onInput(ev) {
        this.props.onChange(ev.target.value || false);
    }
}
mobileFieldRegistry.add("password", PasswordField);

// -----------------------------------------------------------------------------
// color: 只读时显示色块与色值, 编辑时使用系统颜色选择器
// -----------------------------------------------------------------------------

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export class ColorField extends Component {
    static template = xml`
        <t t-name="mobile_web.ColorField">
            <div t-if="this.props.readonly" class="m_field_color">
                <span class="m_field_color_swatch" t-att-style="'background-color: ' + this.color"/>
                <span class="m_field_value"><t t-esc="this.color"/></span>
            </div>
            <input t-else="" type="color" class="m_input m_input_color" t-att-value="this.color" t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get color() {
        const value = this.props.record.data[this.props.name];
        return typeof value === "string" && HEX_COLOR.test(value) ? value : "#000000";
    }
    onInput(ev) {
        this.props.onChange(ev.target.value);
    }
}
mobileFieldRegistry.add("color", ColorField);

// -----------------------------------------------------------------------------
// progressbar: 只读时显示进度条与百分比; 编辑时输入数值
// -----------------------------------------------------------------------------

export class ProgressBarField extends Component {
    static components = { NumberField };
    static template = xml`
        <t t-name="mobile_web.ProgressBarField">
            <div t-if="this.props.readonly" class="m_progressbar" role="progressbar"
                 t-att-aria-valuenow="this.percent" aria-valuemin="0" aria-valuemax="100">
                <div class="m_progressbar_fill" t-att-style="'width: ' + this.percent + '%'"/>
                <span class="m_progressbar_label"><t t-esc="this.percent"/>%</span>
            </div>
            <NumberField t-else="" t-props="this.props"/>
        </t>
    `;
    props = useProps(fieldProps);

    get percent() {
        const value = Number(this.props.record.data[this.props.name]) || 0;
        return Math.min(100, Math.max(0, Math.round(value)));
    }
}
mobileFieldRegistry.add("progressbar", ProgressBarField);

// -----------------------------------------------------------------------------
// json: 只读时以格式化文本显示; 编辑时直接修改 JSON 文本, 解析失败时不保存
// -----------------------------------------------------------------------------

export class JsonField extends Component {
    static template = xml`
        <t t-name="mobile_web.JsonField">
            <pre t-if="this.props.readonly" class="m_field_value m_field_json"><t t-esc="this.text"/></pre>
            <textarea t-else="" class="m_input m_textarea m_field_json" rows="6" t-att-value="this.text" t-on-change="this.onInput"></textarea>
        </t>
    `;
    props = useProps(fieldProps);

    get text() {
        const value = this.props.record.data[this.props.name];
        return value === undefined || value === null || value === false ? "" : JSON.stringify(value, null, 2);
    }
    onInput(ev) {
        try {
            this.props.onChange(JSON.parse(ev.target.value || "null"));
        } catch {
            // 非法 JSON 不保存, 保留用户的输入
        }
    }
}
mobileFieldRegistry.add("json", JsonField);

// -----------------------------------------------------------------------------
// handle: 桌面端列表的拖拽排序手柄. 移动端列表与看板不显示手柄 (见 views/arch.js),
// 因此这里不渲染任何内容, 只为了让带有该控件的视图能正常加载
// -----------------------------------------------------------------------------

export class HandleField extends Component {
    static template = xml`
        <t t-name="mobile_web.HandleField">
            <span class="m_handle_hidden"/>
        </t>
    `;
    props = useProps(fieldProps);
}
mobileFieldRegistry.add("handle", HandleField);

// -----------------------------------------------------------------------------
// image_url: 图片地址; 只读时显示图片, 可编辑时输入地址并预览
// -----------------------------------------------------------------------------

export class ImageUrlField extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.ImageUrlField">
            <div class="m_image_url">
                <img t-if="this.url" class="m_image_url_preview" t-att-src="this.url" alt=""/>
                <input t-if="!this.props.readonly" type="url" class="o_input"
                       t-att-value="this.url || ''" t-att-placeholder="this.props.attrs.placeholder || ''"
                       t-on-change="this.onChange"/>
            </div>
        </t>
    `;
    props = useProps(fieldProps);

    get url() {
        const value = this.props.record.data[this.props.name];
        return value || false;
    }
    onChange(ev) {
        this.props.onChange(ev.target.value.trim() || false);
    }
}
mobileFieldRegistry.add("image_url", ImageUrlField);

import { Component, proxy, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/views/fields/field_utils";
import { MobileSelectSheet } from "@mobile_web/views/widgets/select_sheet";
import { deserializeDate, deserializeDateTime, serializeDateTime } from "@web/core/data/l10n/dates";
import { formatDate, formatDateTime, formatFloat, formatInteger, formatMonetary } from "@web/views/fields/formatters";

// -----------------------------------------------------------------------------
// char / email / url / phone
// -----------------------------------------------------------------------------

const LINK_PREFIX = { email: "mailto:", url: "", phone: "tel:" };
const INPUT_TYPE = { email: "email", url: "url", phone: "tel", char: "text" };

export class CharField extends Component {
    static template = xml`
        <t t-name="mobile_web.CharField">
            <t t-if="this.props.readonly">
                <a t-if="this.linkHref" class="m_field_value m_field_link" t-att-href="this.linkHref"><t t-esc="this.displayValue"/></a>
                <span t-else="" class="m_field_value"><t t-esc="this.displayValue"/></span>
            </t>
            <input t-else="" class="m_input" t-att-type="this.inputType" t-att-value="this.displayValue"
                   t-att-placeholder="this.props.attrs.placeholder or ''"
                   t-att-inputmode="this.inputMode" enterkeyhint="done" autocomplete="off"
                   t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get value() {
        return this.props.record.data[this.props.name];
    }
    get displayValue() {
        return displayOrEmpty(this.value);
    }
    get linkHref() {
        const prefix = LINK_PREFIX[this.props.attrs.widget];
        return prefix !== undefined && this.value ? prefix + this.value : null;
    }
    get inputType() {
        return INPUT_TYPE[this.props.attrs.widget] || "text";
    }
    get inputMode() {
        return this.props.attrs.widget === "phone" ? "tel" : undefined;
    }
    onInput(ev) {
        this.props.onChange(ev.target.value.trim() || false);
    }
}
mobileFieldRegistry.add("char", CharField);
mobileFieldRegistry.add("email", CharField);
mobileFieldRegistry.add("url", CharField);
mobileFieldRegistry.add("phone", CharField);

// -----------------------------------------------------------------------------
// text / html
// -----------------------------------------------------------------------------

export class TextField extends Component {
    static template = xml`
        <t t-name="mobile_web.TextField">
            <p t-if="this.props.readonly" class="m_field_value m_field_multiline"><t t-esc="this.displayValue"/></p>
            <textarea t-else="" class="m_input m_textarea" rows="3" t-att-value="this.displayValue"
                      t-att-placeholder="this.props.attrs.placeholder or ''" t-on-change="this.onInput"></textarea>
        </t>
    `;
    props = useProps(fieldProps);

    get displayValue() {
        return displayOrEmpty(this.props.record.data[this.props.name]);
    }
    onInput(ev) {
        this.props.onChange(ev.target.value || false);
    }
}
mobileFieldRegistry.add("text", TextField);

/**
 * html 字段在移动端只读展示纯文本: 编辑 html 需要富文本编辑器, v1 不支持, 避免破坏原有格式
 */
export class HtmlField extends Component {
    static template = xml`
        <p class="m_field_value m_field_multiline"><t t-esc="this.plainText"/></p>
    `;
    props = useProps(fieldProps);

    get plainText() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return "";
        }
        return new DOMParser().parseFromString(raw, "text/html").body.textContent.trim();
    }
}
mobileFieldRegistry.add("html", HtmlField);

// -----------------------------------------------------------------------------
// integer / float / monetary
// -----------------------------------------------------------------------------

export class NumberField extends Component {
    static template = xml`
        <t t-name="mobile_web.NumberField">
            <span t-if="this.props.readonly" class="m_field_value m_field_number"><t t-esc="this.displayValue"/></span>
            <input t-else="" class="m_input m_input_number" type="number" t-att-inputmode="this.inputMode"
                   step="any" t-att-value="this.props.record.data[this.props.name] or ''"
                   t-att-placeholder="this.props.attrs.placeholder or ''" enterkeyhint="done" t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get inputMode() {
        return this.props.field.type === "integer" ? "numeric" : "decimal";
    }
    get displayValue() {
        const value = this.props.record.data[this.props.name];
        if (value === false || value === undefined) {
            return "";
        }
        if (this.props.field.type === "integer") {
            return formatInteger(value);
        }
        if (this.props.field.type === "monetary") {
            const currency = this.props.record.data[this.props.attrs.currency_field || "currency_id"];
            return formatMonetary(value, { currencyId: currency ? currency[0] : undefined });
        }
        return formatFloat(value);
    }
    onInput(ev) {
        const raw = ev.target.value;
        if (raw === "") {
            this.props.onChange(false);
            return;
        }
        const parsed = this.props.field.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
        this.props.onChange(Number.isNaN(parsed) ? false : parsed);
    }
}
mobileFieldRegistry.add("integer", NumberField);
mobileFieldRegistry.add("float", NumberField);
mobileFieldRegistry.add("monetary", NumberField);

// -----------------------------------------------------------------------------
// boolean (开关)
// -----------------------------------------------------------------------------

export class BooleanField extends Component {
    static template = xml`
        <t t-name="mobile_web.BooleanField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.label"/></span>
            <label t-else="" class="m_switch">
                <input type="checkbox" t-att-checked="!!this.props.record.data[this.props.name]" t-on-change="this.onInput"/>
                <span class="m_switch_track"></span>
                <span class="m_switch_label"><t t-esc="this.label"/></span>
            </label>
        </t>
    `;
    props = useProps(fieldProps);

    get label() {
        return this.props.record.data[this.props.name] ? "是" : "否";
    }
    onInput(ev) {
        this.props.onChange(ev.target.checked);
    }
}
mobileFieldRegistry.add("boolean", BooleanField);

// -----------------------------------------------------------------------------
// selection (底部弹层选择)
// -----------------------------------------------------------------------------

export class SelectionField extends Component {
    static components = { MobileSelectSheet };
    static template = xml`
        <t t-name="mobile_web.SelectionField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.label"/></span>
            <t t-else="">
                <button type="button" class="m_picker_button" t-on-click="this.openSheet">
                    <span t-if="this.hasValue" class="m_picker_value"><t t-esc="this.label"/></span>
                    <span t-else="" class="m_picker_placeholder">请选择</span>
                    <span class="m_picker_caret">›</span>
                </button>
                <MobileSelectSheet t-if="this.state.open" title="this.props.field.string"
                    options="this.options" selected="this.currentIds" allowClear="true"
                    onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    state = proxy({ open: false });

    get currentValue() {
        return this.props.record.data[this.props.name];
    }
    get hasValue() {
        return this.currentValue !== false && this.currentValue !== undefined;
    }
    get options() {
        return (this.props.field.selection || []).map(([value, label]) => ({ id: value, name: label }));
    }
    get currentIds() {
        return this.hasValue ? [{ id: this.currentValue, name: this.label }] : [];
    }
    get label() {
        const option = this.options.find((o) => o.id === this.currentValue);
        return option ? option.name : displayOrEmpty(this.currentValue);
    }
    openSheet() {
        this.state.open = true;
    }
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        this.props.onChange(selected.length ? selected[0].id : false);
        this.close();
    };
}
mobileFieldRegistry.add("selection", SelectionField);

// -----------------------------------------------------------------------------
// date / datetime (原生日期控件)
// -----------------------------------------------------------------------------

export class DateField extends Component {
    static template = xml`
        <t t-name="mobile_web.DateField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayValue"/></span>
            <input t-else="" class="m_input m_input_date" type="date" t-att-value="this.props.record.data[this.props.name] or ''" t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get displayValue() {
        const value = this.props.record.data[this.props.name];
        return value ? formatDate(deserializeDate(value)) : "";
    }
    onInput(ev) {
        this.props.onChange(ev.target.value || false);
    }
}
mobileFieldRegistry.add("date", DateField);

export class DateTimeField extends Component {
    static template = xml`
        <t t-name="mobile_web.DateTimeField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayValue"/></span>
            <input t-else="" class="m_input m_input_datetime" type="datetime-local" t-att-value="this.inputValue" t-on-change="this.onInput"/>
        </t>
    `;
    props = useProps(fieldProps);

    get displayValue() {
        const value = this.props.record.data[this.props.name];
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }
    /** 服务端为 UTC 字符串, 输入框使用本地时间 */
    get inputValue() {
        const value = this.props.record.data[this.props.name];
        return value ? deserializeDateTime(value).toFormat("yyyy-LL-dd'T'HH:mm") : "";
    }
    onInput(ev) {
        if (!ev.target.value) {
            this.props.onChange(false);
            return;
        }
        const local = luxon.DateTime.fromFormat(ev.target.value, "yyyy-LL-dd'T'HH:mm");
        this.props.onChange(serializeDateTime(local));
    }
}
mobileFieldRegistry.add("datetime", DateTimeField);

// -----------------------------------------------------------------------------
// fallback: 未实现的字段类型只读展示, 不影响整个表单
// -----------------------------------------------------------------------------

export class FallbackField extends Component {
    static template = xml`
        <span class="m_field_value"><t t-esc="this.displayValue"/></span>
    `;
    props = useProps(fieldProps);

    get displayValue() {
        const value = this.props.record.data[this.props.name];
        if (Array.isArray(value)) {
            return value.map((pair) => (Array.isArray(pair) ? pair[1] : pair)).join(", ");
        }
        return displayOrEmpty(value);
    }
}
mobileFieldRegistry.add("fallback", FallbackField);

import { Component, signal, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { useInputField } from "@web/views/fields/input_field_hook";
import { formatFloatTime, formatPercentage } from "@web/views/fields/formatters";
import { InvalidNumberError, parseFloatTime, parsePercentage } from "@web/views/fields/parsers";

/** 相对运算的写法, 如 "+=2"; 移动端不提交 Operation 对象, 直接视为无效输入 */
const R_RELATIVE_OPERATION = /^[+\-*/]\s*=/;

/**
 * 数值字段的公共输入逻辑: 编辑时显示可读的数值, 解析交给 web 的解析函数
 */
class NumericBase extends Component {
    props = useProps(fieldProps);
    input = signal.ref();

    setup() {
        useInputField({
            ref: this.input,
            getValue: () => this.editValue,
            parse: (raw) => this.parse(raw),
        });
    }

    get value() {
        const value = this.props.record.data[this.props.name];
        return value === undefined ? false : value;
    }
    get displayValue() {
        return this.value === false ? "" : this.format(this.value, false);
    }
    get editValue() {
        return this.value === false ? "" : this.format(this.value, true);
    }
    /**
     * 子类实现: 存储值 -> 界面文字
     * @returns {string}
     */
    format(value, forEdit) {
        throw new Error("format() must be implemented by the subclass");
    }
    /**
     * 子类实现: 界面文字 -> 存储值, 无效时抛出
     * @returns {number|false}
     */
    parse(raw) {
        throw new Error("parse() must be implemented by the subclass");
    }
    checkRelative(raw) {
        if (R_RELATIVE_OPERATION.test(raw.trim())) {
            throw new InvalidNumberError(raw);
        }
    }
}

// -----------------------------------------------------------------------------
// percentage: 数据库中存储小数(0.5 表示 50%), 界面显示与输入为百分数
// -----------------------------------------------------------------------------

export class PercentageField extends NumericBase {
    static template = xml`
        <t t-name="mobile_web.PercentageField">
            <span t-if="this.props.readonly" class="m_field_value m_field_number"><t t-esc="this.displayValue"/></span>
            <input t-else="" t-ref="this.input" class="m_input m_input_number" type="text" inputmode="decimal"
                   t-att-value="this.editValue" t-att-placeholder="this.props.attrs.placeholder or ''" enterkeyhint="done"/>
        </t>
    `;

    format(value, forEdit) {
        return formatPercentage(value, { noSymbol: forEdit });
    }
    parse(raw) {
        if (raw.trim() === "") {
            return false;
        }
        this.checkRelative(raw);
        return parsePercentage(raw.replace(/%\s*$/, ""));
    }
}
mobileFieldRegistry.add("percentage", PercentageField);

// -----------------------------------------------------------------------------
// float_time: 数据库中存储小时数, 界面显示为 时:分, 输入时也接受 时:分
// -----------------------------------------------------------------------------

export class FloatTimeField extends NumericBase {
    static template = xml`
        <t t-name="mobile_web.FloatTimeField">
            <span t-if="this.props.readonly" class="m_field_value m_field_number"><t t-esc="this.displayValue"/></span>
            <input t-else="" t-ref="this.input" class="m_input m_input_number" type="text" inputmode="text"
                   t-att-value="this.editValue" t-att-placeholder="this.props.attrs.placeholder or ''" enterkeyhint="done"/>
        </t>
    `;

    format(value) {
        return formatFloatTime(value);
    }
    parse(raw) {
        if (raw.trim() === "") {
            return false;
        }
        this.checkRelative(raw);
        const hours = parseFloatTime(raw);
        if (typeof hours !== "number") {
            throw new InvalidNumberError(raw);
        }
        return hours;
    }
}
mobileFieldRegistry.add("float_time", FloatTimeField);

import { Component, proxy, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 选择字段的公共逻辑: 选项为 [value, label] 列表, 当前值与选项按 === 比较
 */
class SelectionBase extends Component {
    texts = fieldTexts;
    props = useProps(fieldProps);

    get options() {
        return this.props.field.selection || [];
    }
    get currentValue() {
        return this.props.record.data[this.props.name];
    }
    get currentIndex() {
        return this.options.findIndex((option) => option[0] === this.currentValue);
    }
    get label() {
        const option = this.options[this.currentIndex];
        return option ? option[1] : displayOrEmpty(this.currentValue);
    }
}

// -----------------------------------------------------------------------------
// radio: 单选按钮组, 选项较少时直接显示全部选项
// -----------------------------------------------------------------------------

export class RadioField extends SelectionBase {
    static template = xml`
        <t t-name="mobile_web.RadioField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.label"/></span>
            <div t-else="" class="m_radio_group" role="radiogroup">
                <label t-foreach="this.options" t-as="option" t-key="option_index" class="m_radio">
                    <input type="radio" t-att-name="this.props.name" t-att-value="option_index"
                           t-att-checked="option_index === this.currentIndex" t-on-change="this.onChange"/>
                    <span class="m_radio_label"><t t-esc="option[1]"/></span>
                </label>
            </div>
        </t>
    `;

    onChange(ev) {
        this.props.onChange(this.options[Number(ev.target.value)][0]);
    }
}
mobileFieldRegistry.add("radio", RadioField);

// -----------------------------------------------------------------------------
// statusbar: 表单头部的状态条, 点击选项即切换状态
// -----------------------------------------------------------------------------

export class StatusBarField extends SelectionBase {
    // 只读的状态显示: 只展示当前状态, 不展示其余选项, 也不能点击修改
    static template = xml`
        <t t-name="mobile_web.StatusBarField">
            <div class="m_statusbar" role="status">
                <span class="m_statusbar_item is_active"><t t-esc="this.label"/></span>
            </div>
        </t>
    `;
}
mobileFieldRegistry.add("statusbar", StatusBarField);

// -----------------------------------------------------------------------------
// priority: 星级, 第一个选项表示"无星", 其余选项各对应一颗星
// -----------------------------------------------------------------------------

export class PriorityField extends SelectionBase {
    static template = xml`
        <t t-name="mobile_web.PriorityField">
            <span t-if="this.props.readonly" class="m_field_value m_priority_text"><t t-esc="this.starText"/></span>
            <div t-else="" class="m_priority">
                <button type="button" t-foreach="this.stars" t-as="star" t-key="star.index"
                        t-attf-class="m_priority_star {{ star.active ? 'is_active' : '' }}"
                        t-att-aria-label="star.label" t-att-title="star.label"
                        t-att-data-index="star.index" t-on-click="this.onClick">★</button>
            </div>
        </t>
    `;

    /** 每颗星对应一个选项(跳过第一个"无星"选项) */
    get stars() {
        const current = Math.max(this.currentIndex, 0);
        return this.options.slice(1).map((option, i) => ({
            index: i + 1,
            label: option[1],
            active: i + 1 <= current && this.currentIndex > 0,
        }));
    }

    get starText() {
        const filled = this.stars.filter((star) => star.active).length;
        return "★".repeat(filled) + "☆".repeat(this.stars.length - filled);
    }

    onClick(ev) {
        const index = Number(ev.currentTarget.dataset.index);
        // 再次点击当前最高的星, 清除评级
        const value = index === this.currentIndex ? this.options[0][0] : this.options[index][0];
        this.props.onChange(value);
    }
}
mobileFieldRegistry.add("priority", PriorityField);

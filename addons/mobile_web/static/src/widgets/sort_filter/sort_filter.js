import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    filterBy: _t("Filter by"),
    value: _t("Value"),
    all: _t("All"),
};

/**
 * 筛选栏: 选择一个筛选字段及其值 (排序由工具条中的排序菜单负责).
 * 每次变化都通过 onChange 回传 { filter }, 由列表或看板决定如何查询.
 */
export class SortFilterBar extends Component {
    texts = TEXTS;
    fieldTexts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.SortFilterBar">
            <div class="m_sort_filter">
                <select class="m_sort_filter_select" t-att-aria-label="this.texts.filterBy" t-on-change="this.onFilterName">
                    <option value=""><t t-esc="this.texts.filterBy"/></option>
                    <option t-foreach="this.props.filterFields" t-as="filter" t-key="filter.name" t-att-value="filter.name"
                            t-att-selected="filter.name === this.state.filterName"><t t-esc="filter.label"/></option>
                </select>
                <t t-if="this.filterField">
                    <select t-if="this.filterOptions" class="m_sort_filter_select" t-on-change="this.onFilterValue">
                        <option value=""><t t-esc="this.texts.all"/></option>
                        <option t-foreach="this.filterOptions" t-as="option" t-key="option[0]" t-att-value="option[0]"
                                t-att-selected="option[0] === this.state.filterValue"><t t-esc="option[1]"/></option>
                    </select>
                    <input t-else="" type="text" class="m_sort_filter_input" t-att-value="this.state.filterValue"
                           t-att-aria-label="this.texts.value" t-att-placeholder="this.texts.value"
                           enterkeyhint="search" t-on-change="this.onFilterValue"/>
                </t>
            </div>
        </t>
    `;
    props = useProps({
        filterFields: t.array(),
        onChange: t.function(),
    });
    state = proxy({ filterName: "", filterValue: "" });

    get filterField() {
        return this.props.filterFields.find((f) => f.name === this.state.filterName) || null;
    }

    /** 选择类字段与布尔字段使用下拉选择, 其余使用文本输入 */
    get filterOptions() {
        const field = this.filterField;
        if (!field) {
            return null;
        }
        if (field.type === "boolean") {
            return [
                ["true", this.fieldTexts.yes],
                ["false", this.fieldTexts.no],
            ];
        }
        if (field.type === "selection") {
            return (field.selection || []).map(([value, label]) => [String(value), label]);
        }
        return null;
    }

    emit() {
        const field = this.filterField;
        const filter = field ? { name: field.name, type: field.type, value: this.state.filterValue } : null;
        this.props.onChange({ filter });
    }

    onFilterName(ev) {
        this.state.filterName = ev.target.value;
        this.state.filterValue = "";
        this.emit();
    }

    onFilterValue(ev) {
        this.state.filterValue = ev.target.value.trim();
        this.emit();
    }
}

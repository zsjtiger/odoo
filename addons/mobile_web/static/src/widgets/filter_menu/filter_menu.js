import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    filter: _t("Filter"),
    chooseField: _t("Choose a filter"),
    noFilters: _t("No filters yet"),
    add: _t("Add"),
    clear: _t("Clear"),
    removeFilter: _t("Remove filter"),
    value: _t("Value"),
    all: _t("All"),
};

/**
 * 筛选菜单: 放在列表/看板的工具条中.
 *
 * 展开后: 上方是待添加的筛选条件 (可移除), 下方选择一个筛选字段并填写值, 点击"添加"加入列表;
 * 已加入的字段不再出现在下拉框中. 底部: 清除 (删除全部条件并立即查询), 取消 (放弃未确定的改动),
 * 确定 (应用全部条件). 只有确定之后才会通过 onChange 回传 { filters }.
 */
export class FilterMenu extends Component {
    texts = TEXTS;
    fieldTexts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.FilterMenu">
            <div class="m_filter_menu">
                <button type="button" t-attf-class="m_filter_menu_toggle {{ this.activeCount ? 'is_active' : '' }}"
                        t-att-aria-expanded="this.state.open ? 'true' : 'false'" t-on-click="this.toggle">
                    <t t-esc="this.texts.filter"/><t t-if="this.activeCount"> (<t t-esc="this.activeCount"/>)</t>
                    <t t-esc="this.state.open ? ' ▲' : ' ▼'"/>
                </button>
                <t t-if="this.state.open">
                    <div class="m_filter_menu_backdrop" t-on-click="this.cancel"/>
                    <div class="m_filter_menu_panel" role="dialog">
                        <ul t-if="this.state.pending.length" class="m_filter_chips">
                            <li t-foreach="this.state.pending" t-as="item" t-key="item.name" class="m_filter_chip">
                                <span class="m_filter_chip_text"><t t-esc="item.label"/>: <t t-esc="this.displayValue(item)"/></span>
                                <button type="button" class="m_filter_chip_remove" t-att-data-index="item_index"
                                        t-att-aria-label="this.texts.removeFilter" t-on-click="this.onRemove">×</button>
                            </li>
                        </ul>
                        <p t-else="" class="m_filter_empty"><t t-esc="this.texts.noFilters"/></p>
                        <div class="m_filter_add">
                            <select class="m_filter_select" t-att-aria-label="this.texts.chooseField" t-on-change="this.onPickField">
                                <option value=""><t t-esc="this.texts.chooseField"/></option>
                                <option t-foreach="this.availableFields" t-as="field" t-key="field.name" t-att-value="field.name"
                                        t-att-selected="field.name === this.state.draft.name"><t t-esc="field.label"/></option>
                            </select>
                            <t t-if="this.draftField">
                                <select t-if="this.draftOptions" class="m_filter_select" t-att-aria-label="this.texts.value" t-on-change="this.onValue">
                                    <option value=""><t t-esc="this.texts.all"/></option>
                                    <option t-foreach="this.draftOptions" t-as="option" t-key="option[0]" t-att-value="option[0]"
                                            t-att-selected="option[0] === this.state.draft.value"><t t-esc="option[1]"/></option>
                                </select>
                                <input t-else="" type="text" class="m_filter_input" t-att-value="this.state.draft.value"
                                       t-att-placeholder="this.texts.value" t-att-aria-label="this.texts.value"
                                       enterkeyhint="done" t-on-change="this.onValue"/>
                                <button type="button" class="m_filter_add_btn" t-att-disabled="!this.canAdd or null" t-on-click="this.onAdd">
                                    <t t-esc="this.texts.add"/>
                                </button>
                            </t>
                        </div>
                        <div class="m_filter_footer">
                            <button type="button" class="m_filter_btn m_filter_clear" t-on-click="this.onClear"><t t-esc="this.texts.clear"/></button>
                            <button type="button" class="m_filter_btn m_filter_cancel" t-on-click="this.cancel"><t t-esc="this.fieldTexts.cancel"/></button>
                            <button type="button" class="m_filter_btn m_filter_confirm" t-on-click="this.onConfirm"><t t-esc="this.fieldTexts.confirm"/></button>
                        </div>
                    </div>
                </t>
            </div>
        </t>
    `;
    props = useProps({
        filterFields: t.array(),
        onChange: t.function(),
    });
    // committed: 已确定、正在生效的条件; pending: 面板中正在编辑的条件; draft: 下拉框中当前选择的字段与值
    state = proxy({
        open: false,
        committed: [],
        pending: [],
        draft: { name: "", value: "" },
    });

    get activeCount() {
        return this.state.committed.length;
    }

    /** 已加入待定列表的字段不再出现在下拉框中 */
    get availableFields() {
        return this.props.filterFields.filter((field) => !this.state.pending.some((item) => item.name === field.name));
    }

    get draftField() {
        return this.props.filterFields.find((field) => field.name === this.state.draft.name) || null;
    }

    /** 选择类字段与布尔字段使用下拉选择, 其余使用文本输入 */
    get draftOptions() {
        const field = this.draftField;
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

    get canAdd() {
        return Boolean(this.draftField) && this.state.draft.value !== "";
    }

    /** 条件的显示值: 布尔与选择显示其文字 */
    displayValue(item) {
        if (item.type === "boolean") {
            return item.value === "true" ? this.fieldTexts.yes : this.fieldTexts.no;
        }
        if (item.type === "selection") {
            const option = (item.selection || []).find(([value]) => String(value) === item.value);
            return option ? option[1] : item.value;
        }
        return item.value;
    }

    resetDraft() {
        this.state.draft.name = "";
        this.state.draft.value = "";
    }

    toggle() {
        if (!this.state.open) {
            // 每次打开都从已确定的条件开始, 未确定的改动不会残留
            this.state.pending = this.state.committed.map((item) => ({ ...item }));
            this.resetDraft();
        }
        this.state.open = !this.state.open;
    }

    /** 取消: 放弃未确定的改动 */
    cancel() {
        this.state.open = false;
    }

    onPickField(ev) {
        this.state.draft.name = ev.target.value;
        this.state.draft.value = "";
    }

    onValue(ev) {
        this.state.draft.value = ev.target.value.trim();
    }

    onAdd() {
        if (!this.canAdd) {
            return;
        }
        const field = this.draftField;
        this.state.pending.push({
            name: field.name,
            type: field.type,
            label: field.label,
            selection: field.selection,
            value: this.state.draft.value,
        });
        this.resetDraft();
    }

    onRemove(ev) {
        this.state.pending.splice(Number(ev.currentTarget.dataset.index), 1);
    }

    onConfirm() {
        this.state.committed = this.state.pending.map((item) => ({ ...item }));
        this.state.open = false;
        this.emit();
    }

    onClear() {
        this.state.committed = [];
        this.state.pending = [];
        this.resetDraft();
        this.state.open = false;
        this.emit();
    }

    emit() {
        const filters = this.state.committed.map(({ name, type, value }) => ({ name, type, value }));
        this.props.onChange({ filters });
    }
}

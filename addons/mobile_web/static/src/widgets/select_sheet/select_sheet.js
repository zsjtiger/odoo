import { Component, onWillStart, onWillUnmount, proxy, t, useProps, xml } from "@odoo/owl";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 移动端的底部弹层选择器: 用于 selection / many2one / many2many
 *
 * - 单选: 点选即确定
 * - 多选: 勾选后点"确定"
 * - 选项可以是静态列表(options), 也可以是按关键字搜索的异步函数(search)
 *
 * 选项格式统一为 {id, name}
 */
export class MobileSelectSheet extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.MobileSelectSheet">
            <div class="m_sheet_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_sheet" role="dialog">
                    <header class="m_sheet_header">
                        <button type="button" class="m_sheet_btn" t-on-click="this.onCancel"><t t-esc="this.texts.cancel"/></button>
                        <span class="m_sheet_title"><t t-esc="this.props.title"/></span>
                        <button t-if="this.props.multiple" type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.onConfirmMulti"><t t-esc="this.texts.confirm"/></button>
                        <span t-else="" class="m_sheet_btn_spacer"></span>
                    </header>
                    <div class="m_sheet_search">
                        <input type="search" class="m_input" t-att-placeholder="this.texts.search" enterkeyhint="search"
                               t-att-value="this.state.text" t-on-input="this.onSearchInput"/>
                    </div>
                    <ul class="m_sheet_list">
                        <li t-if="this.props.allowClear">
                            <button type="button" class="m_sheet_item m_sheet_item_clear" t-on-click="this.onClear"><t t-esc="this.texts.clearSelection"/></button>
                        </li>
                        <t t-foreach="this.state.items" t-as="item" t-key="item.id">
                            <li>
                                <button type="button" t-attf-class="m_sheet_item {{ this.isSelected(item) ? 'is_selected' : '' }}"
                                        t-att-data-index="item_index" t-on-click="this.onItemClick">
                                    <span class="m_sheet_item_name"><t t-esc="item.name"/></span>
                                    <span t-if="this.isSelected(item)" class="m_sheet_check">✓</span>
                                </button>
                            </li>
                        </t>
                        <li t-if="this.state.loading" class="m_sheet_status"><t t-esc="this.texts.loading"/></li>
                        <li t-elif="!this.state.items.length" class="m_sheet_status"><t t-esc="this.texts.noMatch"/></li>
                    </ul>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        title: t.string().optional(""),
        options: t.array().optional([]),
        search: t.function().optional(),
        selected: t.array().optional([]),
        multiple: t.boolean().optional(false),
        allowClear: t.boolean().optional(false),
        onConfirm: t.function(),
        onClose: t.function(),
    });

    state = proxy({
        items: [],
        text: "",
        loading: false,
        selected: [],
    });

    setup() {
        this.state.selected = [...(this.props.selected || [])];
        this.debounceTimer = null;
        onWillStart(() => this.load(""));
        onWillUnmount(() => clearTimeout(this.debounceTimer));
    }

    async load(text) {
        if (!this.props.search) {
            const lower = text.toLowerCase();
            this.state.items = (this.props.options || []).filter((o) => o.name.toLowerCase().includes(lower));
            return;
        }
        this.state.loading = true;
        try {
            this.state.items = await this.props.search(text);
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        this.state.text = ev.target.value;
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => this.load(this.state.text), 250);
    }

    isSelected(item) {
        return this.state.selected.some((s) => s.id === item.id);
    }

    onItemClick(ev) {
        const item = this.state.items[Number(ev.currentTarget.dataset.index)];
        if (!item) {
            return;
        }
        if (this.props.multiple) {
            this.state.selected = this.isSelected(item)
                ? this.state.selected.filter((s) => s.id !== item.id)
                : [...this.state.selected, item];
            return;
        }
        this.props.onConfirm([item]);
    }

    onClear() {
        this.props.onConfirm([]);
    }

    onConfirmMulti() {
        this.props.onConfirm(this.state.selected);
    }

    onCancel() {
        this.props.onClose();
    }

    onBackdropClick(ev) {
        if (ev.target.classList.contains("m_sheet_backdrop")) {
            this.props.onClose();
        }
    }
}

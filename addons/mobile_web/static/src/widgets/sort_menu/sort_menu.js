import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { orderString } from "@mobile_web/views/record_filters";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    sort: _t("Sort"),
    defaultOrder: _t("Default order"),
    ascending: _t("Ascending"),
    descending: _t("Descending"),
};

/**
 * 排序菜单: 放在列表/看板的工具条中, 点击展开一组单选项.
 * 第一组为排序字段(可选"默认排序"), 选择字段后再选择升序或降序.
 * 每次选择都通过 onChange 回传 { order }, 由列表或看板重新加载.
 */
export class SortMenu extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.SortMenu">
            <div t-attf-class="m_sort_menu {{ this.props.iconOnly ? 'is_icon' : '' }}">
                <button t-if="this.props.iconOnly" type="button" t-attf-class="m_sort_menu_toggle m_sort_menu_icon {{ this.state.sortName ? 'is_active' : '' }}"
                        t-att-aria-label="this.texts.sort" t-att-aria-expanded="this.state.open ? 'true' : 'false'" t-on-click="this.toggle">
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M7 4v16M3.5 7.5 7 4l3.5 3.5M17 20V4m-3.5 3.5L17 4l3.5 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                <button t-else="" type="button" t-attf-class="m_sort_menu_toggle {{ this.state.sortName ? 'is_active' : '' }}"
                        t-att-aria-expanded="this.state.open ? 'true' : 'false'" t-on-click="this.toggle">
                    <t t-esc="this.texts.sort"/> <t t-esc="this.state.open ? '▲' : '▼'"/>
                </button>
                <t t-if="this.state.open">
                    <div class="m_sort_menu_backdrop" t-on-click="this.close"/>
                    <ul class="m_sort_menu_panel" role="listbox">
                        <li>
                            <button type="button" class="m_sort_menu_item" role="option" data-name=""
                                    t-att-aria-selected="this.state.sortName ? 'false' : 'true'" t-on-click="this.onPickField">
                                <span class="m_sort_menu_check"><t t-esc="this.state.sortName ? '' : '✓'"/></span>
                                <t t-esc="this.texts.defaultOrder"/>
                            </button>
                        </li>
                        <li t-foreach="this.props.sortFields" t-as="sort" t-key="sort.name">
                            <button type="button" class="m_sort_menu_item" role="option" t-att-data-name="sort.name"
                                    t-att-aria-selected="this.state.sortName === sort.name ? 'true' : 'false'" t-on-click="this.onPickField">
                                <span class="m_sort_menu_check"><t t-esc="this.state.sortName === sort.name ? '✓' : ''"/></span>
                                <t t-esc="sort.label"/>
                            </button>
                        </li>
                        <t t-if="this.state.sortName">
                            <li class="m_sort_menu_divider" role="separator"/>
                            <li>
                                <button type="button" class="m_sort_menu_item" role="option" data-dir="asc"
                                        t-att-aria-selected="this.state.sortDir === 'asc' ? 'true' : 'false'" t-on-click="this.onPickDir">
                                    <span class="m_sort_menu_check"><t t-esc="this.state.sortDir === 'asc' ? '✓' : ''"/></span>
                                    <t t-esc="this.texts.ascending"/>
                                </button>
                            </li>
                            <li>
                                <button type="button" class="m_sort_menu_item" role="option" data-dir="desc"
                                        t-att-aria-selected="this.state.sortDir === 'desc' ? 'true' : 'false'" t-on-click="this.onPickDir">
                                    <span class="m_sort_menu_check"><t t-esc="this.state.sortDir === 'desc' ? '✓' : ''"/></span>
                                    <t t-esc="this.texts.descending"/>
                                </button>
                            </li>
                        </t>
                    </ul>
                </t>
            </div>
        </t>
    `;
    props = useProps({
        sortFields: t.array(),
        onChange: t.function(),
        // 只显示图标 (放在搜索栏右侧时使用)
        iconOnly: t.boolean().optional(false),
    });
    state = proxy({ open: false, sortName: "", sortDir: /** @type {"asc" | "desc"} */ ("asc") });

    toggle() {
        this.state.open = !this.state.open;
    }

    close() {
        this.state.open = false;
    }

    emit() {
        const sort = this.state.sortName ? { name: this.state.sortName, dir: this.state.sortDir } : null;
        this.props.onChange({ order: orderString(sort) });
    }

    onPickField(ev) {
        this.state.sortName = ev.currentTarget.dataset.name || "";
        this.state.open = false;
        this.emit();
    }

    onPickDir(ev) {
        this.state.sortDir = ev.currentTarget.dataset.dir === "desc" ? "desc" : "asc";
        this.state.open = false;
        this.emit();
    }
}

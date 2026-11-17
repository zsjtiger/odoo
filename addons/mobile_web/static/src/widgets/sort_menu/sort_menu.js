import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";
import { orderStringMany } from "@mobile_web/views/record_filters";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    sort: _t("Sort"),
};

/**
 * 排序面板: 搜索栏右侧的图标打开, 每个可排序字段是一个按钮.
 * 点击一次为升序, 再点一次为降序, 第三次取消; 可以同时选择多个字段 (按选择的先后排序).
 * 确认后通过 onChange 回传 { order }, 由列表或看板重新加载.
 */
export class SortMenu extends Component {
    texts = { ...TEXTS, ...fieldTexts };
    static template = xml`
        <t t-name="mobile_web.SortMenu">
            <div class="m_sort_menu is_icon">
                <button type="button" t-attf-class="m_sort_menu_toggle m_sort_menu_icon {{ this.state.applied.length ? 'is_active' : '' }}"
                        t-att-aria-label="this.texts.sort" t-att-aria-expanded="this.state.open ? 'true' : 'false'" t-on-click="this.open">
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M7 4v16M3.5 7.5 7 4l3.5 3.5M17 20V4m-3.5 3.5L17 4l3.5 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                <div t-if="this.state.open" class="m_sheet_backdrop" t-on-click="this.cancel">
                    <div class="m_sheet m_sort_sheet" role="dialog" t-on-click="this.stop">
                        <header class="m_sheet_header">
                            <button type="button" class="m_sheet_btn" t-on-click="this.cancel"><t t-esc="this.texts.cancel"/></button>
                            <span class="m_sheet_title"><t t-esc="this.texts.sort"/></span>
                            <button type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.confirm"><t t-esc="this.texts.confirm"/></button>
                        </header>
                        <div class="m_sort_body">
                            <div class="m_sort_options">
                                <button t-foreach="this.props.sortFields" t-as="field" t-key="field.name" type="button"
                                        t-attf-class="m_sort_chip {{ this.directionOf(field.name) ? 'is_on' : '' }}"
                                        t-att-data-name="field.name" t-on-click="this.toggleField">
                                    <t t-esc="field.label"/><t t-if="this.directionOf(field.name)"> <t t-esc="this.arrowOf(field.name)"/></t>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        sortFields: t.array(),
        onChange: t.function(),
        // 只显示图标 (放在搜索栏右侧时使用); 保留以兼容旧的调用方式
        iconOnly: t.boolean().optional(true),
    });
    // 已应用的排序 与 面板中正在编辑的排序
    state = proxy({ open: false, applied: [], draft: [] });

    stop(ev) {
        ev.stopPropagation();
    }

    open() {
        this.state.draft = [...this.state.applied];
        this.state.open = true;
    }

    cancel() {
        this.state.open = false;
    }

    confirm() {
        this.state.applied = [...this.state.draft];
        this.state.open = false;
        this.props.onChange({ order: orderStringMany(this.state.applied) });
    }

    directionOf(name) {
        return this.state.draft.find((sort) => sort.name === name)?.dir || null;
    }

    arrowOf(name) {
        return this.directionOf(name) === "desc" ? "↓" : "↑";
    }

    /** 未选 -> 升序 -> 降序 -> 取消选择 */
    toggleField(ev) {
        const name = ev.currentTarget.dataset.name;
        const current = this.directionOf(name);
        if (!current) {
            this.state.draft = [...this.state.draft, { name, dir: "asc" }];
        } else if (current === "asc") {
            this.state.draft = this.state.draft.map((sort) => (sort.name === name ? { name, dir: "desc" } : sort));
        } else {
            this.state.draft = this.state.draft.filter((sort) => sort.name !== name);
        }
    }
}

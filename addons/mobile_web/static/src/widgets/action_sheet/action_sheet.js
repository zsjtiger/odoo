import { Component, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    title: _t("Actions"),
};

/**
 * 底部操作弹层: 列出一条记录上可用的操作; 点击后执行并关闭
 */
export class ActionSheet extends Component {
    texts = TEXTS;
    fieldTexts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.ActionSheet">
            <div class="m_sheet_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_sheet" role="dialog">
                    <header class="m_sheet_header">
                        <span class="m_sheet_title"><t t-esc="this.texts.title"/></span>
                    </header>
                    <ul class="m_sheet_list">
                        <li t-foreach="this.props.items" t-as="item" t-key="item.key">
                            <button type="button" class="m_sheet_item" t-att-data-index="item_index" t-on-click="this.onItemClick">
                                <t t-esc="item.label"/>
                            </button>
                        </li>
                    </ul>
                    <button type="button" class="m_sheet_btn m_sheet_cancel" t-on-click="this.props.onClose"><t t-esc="this.fieldTexts.cancel"/></button>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        items: t.array(),
        onClose: t.function(),
    });

    async onItemClick(ev) {
        const item = this.props.items[Number(ev.currentTarget.dataset.index)];
        try {
            await item.run();
        } finally {
            this.props.onClose();
        }
    }

    onBackdropClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.props.onClose();
        }
    }
}

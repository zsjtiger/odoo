import { Component, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    notOpen: _t("Not available yet"),
};

/**
 * 功能尚未开放时的占位提示
 */
export class Unavailable extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.Unavailable">
            <p class="m_empty m_unavailable"><t t-esc="this.texts.notOpen"/></p>
        </t>
    `;
}

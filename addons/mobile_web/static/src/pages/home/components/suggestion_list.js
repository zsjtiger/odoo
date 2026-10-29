import { Component, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";


// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    empty: _t("No suggestions yet"),
};

export class SuggestionList extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.HomePage.SuggestionList">
            <div class="m_home_page_suggestion card">
                <strong><t t-esc="this.texts.empty"/></strong>
            </div>
        </t>
    `;
};

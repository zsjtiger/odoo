import { xml } from '@odoo/owl';
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { _t } from "@web/core/data/l10n/translation";


// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    title: _t("My"),
};

export class UserMyPage extends MobilePage {
    texts = TEXTS;
    static components = {
    }
    static template = xml`
        <t t-name="mobile_web.UserMyPage">
            <div class="m_page">
                <strong><t t-esc="this.texts.title"/></strong>
            </div>
        </t>
    `;
};

mobilePageRegistry.add(PAGE_KEYS.MY, UserMyPage);

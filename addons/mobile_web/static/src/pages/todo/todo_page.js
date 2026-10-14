import { onWillStart, proxy, xml } from "@odoo/owl";
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { Unavailable } from "@mobile_web/pages/shared/components/unavailable";
import { isModelAvailable } from "@mobile_web/pages/shared/data/model_access";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/services/user";
import { _t } from "@web/core/data/l10n/translation";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    title: _t("To do"),
    empty: _t("Nothing to do"),
    loadFailed: _t("Failed to load, please try again"),
};

/** 待办: 当前用户的活动 (mail.activity), 需要安装 mail 模块 */
const MODEL = "mail.activity";

export class TodoPage extends MobilePage {
    texts = TEXTS;
    static components = { Unavailable };
    orm = useService("orm");
    state = proxy({ available: null, items: [], error: false });

    static template = xml`
        <t t-name="mobile_web.TodoPage">
            <div class="m_page">
                <strong><t t-esc="this.texts.title"/></strong>
                <Unavailable t-if="this.state.available === false"/>
                <p t-if="this.state.error" class="m_error"><t t-esc="this.texts.loadFailed"/></p>
                <p t-elif="this.state.available and !this.state.items.length" class="m_empty"><t t-esc="this.texts.empty"/></p>
                <ul class="m_plain_list" t-if="this.state.items.length">
                    <li t-foreach="this.state.items" t-as="item" t-key="item.id">
                        <span class="m_plain_list_title"><t t-esc="item.summary || item.res_name"/></span>
                        <span class="m_plain_list_meta"><t t-esc="item.date_deadline"/></span>
                    </li>
                </ul>
            </div>
        </t>
    `;

    setup() {
        onWillStart(() => this.load());
    }

    async load() {
        this.state.available = await isModelAvailable(this.orm, MODEL);
        if (!this.state.available) {
            return;
        }
        try {
            this.state.items = await this.orm.searchRead(
                MODEL,
                [["user_id", "=", user.userId]],
                ["summary", "res_name", "date_deadline"],
                { order: "date_deadline asc", limit: 50 }
            );
        } catch {
            this.state.error = true;
        }
    }
}

mobilePageRegistry.add(PAGE_KEYS.TODO, TodoPage);

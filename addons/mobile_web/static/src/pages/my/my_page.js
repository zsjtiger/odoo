import { onWillStart, proxy, xml } from "@odoo/owl";
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/services/user";
import { _t } from "@web/core/data/l10n/translation";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    title: _t("My"),
    name: _t("Name"),
    login: _t("Login"),
    email: _t("Email"),
    company: _t("Company"),
    loadFailed: _t("Failed to load, please try again"),
};

/**
 * 我的: 当前登录用户的基本信息
 */
export class UserMyPage extends MobilePage {
    texts = TEXTS;
    orm = useService("orm");
    state = proxy({ rows: [], error: false });

    static template = xml`
        <t t-name="mobile_web.UserMyPage">
            <div class="m_page">
                <strong><t t-esc="this.texts.title"/></strong>
                <p t-if="this.state.error" class="m_error"><t t-esc="this.texts.loadFailed"/></p>
                <dl class="m_my_info" t-if="this.state.rows.length">
                    <t t-foreach="this.state.rows" t-as="row" t-key="row.label">
                        <dt><t t-esc="row.label"/></dt>
                        <dd><t t-esc="row.value"/></dd>
                    </t>
                </dl>
            </div>
        </t>
    `;

    setup() {
        onWillStart(() => this.load());
    }

    async load() {
        try {
            const [record] = await this.orm.read("res.users", [user.userId], ["name", "login", "email", "company_id"]);
            this.state.rows = [
                { label: this.texts.name, value: record.name || "" },
                { label: this.texts.login, value: record.login || "" },
                { label: this.texts.email, value: record.email || "" },
                { label: this.texts.company, value: record.company_id ? record.company_id[1] : "" },
            ];
        } catch {
            this.state.error = true;
        }
    }
}

mobilePageRegistry.add(PAGE_KEYS.MY, UserMyPage);

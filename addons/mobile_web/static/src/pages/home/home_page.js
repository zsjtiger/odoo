import { xml } from '@odoo/owl';
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";

import { UserInfo } from "@mobile_web/pages/home/components/user_info";
import { HomeReport } from "@mobile_web/reports/home_report/home_report";
import { HomeMenu } from "@mobile_web/pages/home/components/home_menu";
import { SuggestionList } from "@mobile_web/pages/home/components/suggestion_list";


export class HomePage extends MobilePage {
    static components = {
        UserInfo,
        HomeReport,
        HomeMenu,
        SuggestionList,
    }
    static template = xml`
        <t t-name="mobile_web.HomePage">
            <div class="m_page m_home_page">
                <UserInfo/>
                <HomeReport/>
                <HomeMenu/>
                <SuggestionList/>
            </div>
        </t>
    `;
};


mobilePageRegistry.add(PAGE_KEYS.HOME, HomePage);

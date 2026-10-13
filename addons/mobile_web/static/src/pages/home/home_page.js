import { xml } from '@odoo/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';
import { PAGE_KEYS } from '../common/page_keys';

import { UserInfo } from './components/user_info';
import { HomeReport } from './components/home_report';
import { HomeMenu } from './components/home_menu';
import { SuggestionList } from './components/suggestion_list';


export class HomePage extends MobilePage {
    static props = {};
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

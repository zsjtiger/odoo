import { xml } from '@odoo/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';
import { PAGE_KEYS } from '../common/page_keys';


export class UserMyPage extends MobilePage {
    static props = {};
    static components = {
    }
    static template = xml`
        <t t-name="mobile_web.UserMyPage">
            <div class="m_page">
                <strong>我的页</strong>
            </div>
        </t>
    `;
};

mobilePageRegistry.add(PAGE_KEYS.MY, UserMyPage);

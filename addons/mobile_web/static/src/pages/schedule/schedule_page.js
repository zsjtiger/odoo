import { xml } from '@odoo/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';
import { PAGE_KEYS } from '../common/page_keys';


export class SchedulePage extends MobilePage {
    static props = {};
    static components = {
    }
    static template = xml`
        <t t-name="mobile_web.SchedulePage">
            <div class="m_page">
                <strong>日程页</strong>
            </div>
        </t>
    `;
};

mobilePageRegistry.add(PAGE_KEYS.SCHEDULE, SchedulePage);

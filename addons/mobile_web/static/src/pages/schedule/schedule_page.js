import { xml } from '@crossnow/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';


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

mobilePageRegistry.add("mobile_page.schedule_page", SchedulePage);

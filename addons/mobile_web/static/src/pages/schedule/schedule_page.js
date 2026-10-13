import { xml } from '@odoo/owl';
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";


export class SchedulePage extends MobilePage {
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

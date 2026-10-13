import { xml } from '@odoo/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';
import { PAGE_KEYS } from '../common/page_keys';


export class TodoPage extends MobilePage {
    static components = {
    }
    static template = xml`
        <t t-name="mobile_web.TodoPage">
            <div class="m_page">
                <strong>待办页</strong>
            </div>
        </t>
    `;
};

mobilePageRegistry.add(PAGE_KEYS.TODO, TodoPage);

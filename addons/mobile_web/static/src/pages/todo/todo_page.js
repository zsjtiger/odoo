import { xml } from '@odoo/owl';
import { MobilePage } from '../common/components/mobile_page';
import { mobilePageRegistry } from '../common/page_registry';


export class TodoPage extends MobilePage {
    static props = {};
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

mobilePageRegistry.add("mobile_page.todo_page", TodoPage);

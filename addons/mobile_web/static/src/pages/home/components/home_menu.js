import { Component, xml, onWillStart } from "@odoo/owl";
import { browser } from "@web/core/services/browser/browser";
import { session } from "@web/boot/session";
import { useService } from "@web/core/utils/hooks";


/** 
 * @typedef {Object} MenuData
 * @property {number|false} id
 * @property {string|false} name
 * @property {number[]} children
 * @property {number|false} appID
 * @property {string|false} xmlid
 * @property {number|false} actionID
 * @property {string|false} actionModel
 * @property {string|false} actionPath
 * @property {string|null|false} webIcon
 * @property {Base64URLString|null} webIconData base64
 * @property {string|null} webIconDataMimetype
 * @property {string|null} [backgroundImage] only root menu
 */


const loadMenusUrl = `/mobile_web/webclient/load_menus`;


// TODO: 这里仅是展示, 如果要涉及到排序等等，考虑创建一个menuService进行管理
export class HomeMenu extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.HomeMenu">
            <div class="m_home_page_menu card">
                <t t-foreach="this.menus" t-as="menu" t-key="menu.id">
                    <t t-if="menu.isPlaceHolder">
                        <div class="menu_item menu_item_placeholder"></div>
                    </t>
                    <t t-else="">
                        <div class="menu_item card" t-att="{'data-action-id': menu.actionID}" t-on-click="this.onMenuItemClick">
                            <div t-if="menu.webIconData">
                                <img t-att-src="menu.webIconData" class="menu_item_icon"/>
                            </div>

                            <div class="menu_item_name">
                                <t t-esc="menu.name"/>
                            </div>
                        </div>
                    </t>
                </t>
            </div>
        </t>
    `;

    setup() {
        this.mobileActionService = useService("mobileAction");

        onWillStart(async () => {
            /** @type {MenuData[]} */
            const allMenuItems = await this._loadMenus();
            
            // flex占位, 一行不足4个的增加占位元素
            const placeHolderNum = (4 - (allMenuItems.length % 4)) % 4;
            this.menus = [...allMenuItems, ...Array(placeHolderNum).fill({isPlaceHolder: true})]
        });
    }

    /**
     * 加载手机端menu数据
     * @returns {Promise<MenuData[]>}
     */
    async _loadMenus() {
        /** @type {Object} */
        const menusData = await this._fetchMenuData();

        // 这里仅筛选含有action_id的
        /** @type {Object[]} */
        const haveActionMenus = Object.values(menusData).filter(el => el.actionID);

        return haveActionMenus;
    }

    /**
     * 从后台加载menu数据
     * @returns {Promise<MenuData[]>}
     */
    async _fetchMenuData() {
        // 此版本的 session 不再提供 cache_hashes, 缺失时使用时间戳, 每次都重新加载菜单
        const loadMenusHash = session.cache_hashes?.load_menus || Date.now().toString();
        const res = await browser.fetch(`${loadMenusUrl}/${loadMenusHash}`);
        if (!res.ok) {
            throw new Error("Error while fetching menus");
        }
        return res.json();
    }

    onMenuItemClick(ev) {
        const actionId = ev.currentTarget.dataset.actionId;
        this.mobileActionService.doAction(actionId);
    }
};

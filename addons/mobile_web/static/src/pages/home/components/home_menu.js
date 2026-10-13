import { Component, onWillStart, proxy, xml } from "@odoo/owl";
import { browser } from "@web/core/services/browser/browser";
import { session } from "@web/boot/session";
import { useService } from "@web/core/utils/hooks";


/**
 * @typedef {Object} MenuData
 * @property {number|false} id
 * @property {string|false} name
 * @property {number|false} actionID
 * @property {string|null|false} webIcon
 * @property {Base64URLString|null} webIconData base64
 */

const loadMenusUrl = `/mobile_web/webclient/load_menus`;

// 5 列 x 3 行, 每页 15 个, 超出时左右滑动翻页
const COLUMNS = 5;
const ROWS_PER_PAGE = 3;
const MENUS_PER_PAGE = COLUMNS * ROWS_PER_PAGE;

// 没有图标的应用使用的底色, 按 id 取色, 保证同一个应用颜色固定
const FALLBACK_COLORS = ["#03a09c", "#f0a030", "#5a7bd8", "#e0624f", "#8a6fd1", "#3aa86b"];


/**
 * 首页应用网格: 图标 + 文字, 没有图标时用首字母色块代替, 超过一页时左右滑动
 */
export class HomeMenu extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.HomeMenu">
            <div class="m_home_menu">
                <div class="m_home_menu_track" t-on-scroll="this.onScroll">
                    <div class="m_home_menu_page" t-foreach="this.pages" t-as="page" t-key="page_index">
                        <button type="button" class="m_home_menu_item"
                                t-foreach="page" t-as="menu" t-key="menu.id"
                                t-att-data-action-id="menu.actionID" t-on-click="this.onMenuItemClick">
                            <img t-if="menu.webIconData" class="m_home_menu_icon" t-att-src="menu.webIconData" alt=""/>
                            <span t-else="" class="m_home_menu_icon m_home_menu_fallback"
                                  t-attf-style="background: {{ this.colorOf(menu) }}"><t t-esc="this.initialOf(menu)"/></span>
                            <span class="m_home_menu_label"><t t-esc="menu.name"/></span>
                        </button>
                    </div>
                </div>
                <div class="m_home_menu_dots" t-if="this.pages.length > 1">
                    <span t-foreach="this.pages" t-as="page" t-key="page_index"
                          t-attf-class="m_home_menu_dot {{ this.state.page === page_index ? 'is_active' : '' }}"></span>
                </div>
            </div>
        </t>
    `;

    setup() {
        this.mobileActionService = useService("mobileAction");
        this.state = proxy({ page: 0 });
        this.pages = [];

        onWillStart(async () => {
            /** @type {MenuData[]} */
            const menus = await this._loadMenus();
            this.pages = chunk(menus, MENUS_PER_PAGE);
        });
    }

    /**
     * 加载手机端 menu 数据, 只保留带动作的应用
     * @returns {Promise<MenuData[]>}
     */
    async _loadMenus() {
        const menusData = await this._fetchMenuData();
        return Object.values(menusData).filter((el) => el.actionID);
    }

    /**
     * 从后台加载 menu 数据
     * @returns {Promise<Object>}
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

    colorOf(menu) {
        return FALLBACK_COLORS[Number(menu.id) % FALLBACK_COLORS.length];
    }

    initialOf(menu) {
        return (menu.name || "?").trim().charAt(0).toUpperCase();
    }

    /** 根据滚动位置计算当前页, 用于底部的页码点 */
    onScroll(ev) {
        const track = ev.currentTarget;
        this.state.page = Math.round(track.scrollLeft / track.clientWidth);
    }

    onMenuItemClick(ev) {
        const actionId = ev.currentTarget.dataset.actionId;
        this.mobileActionService.doAction(actionId);
    }
}

function chunk(items, size) {
    const pages = [];
    for (let i = 0; i < items.length; i += size) {
        pages.push(items.slice(i, i + size));
    }
    return pages;
}

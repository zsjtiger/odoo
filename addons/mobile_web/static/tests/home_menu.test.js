import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { browser } from "@web/core/services/browser/browser";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { HomeMenu } from "@mobile_web/pages/home/components/home_menu";
import { mobileActionCalls, resetMobileActionCalls } from "@mobile_web/../tests/helpers/mobile_action_stub";

describe.current.tags("mobile");

/** doAction 的调用记录, 由公共的 mobileAction 桩服务提供 */
const doActionCalls = mobileActionCalls;

function makeMenus(count, { withIcon = true } = {}) {
    const menus = {};
    for (let i = 0; i < count; i++) {
        menus[i + 1] = {
            id: i + 1,
            name: `App ${i + 1}`,
            actionID: 100 + i,
            webIconData: withIcon ? "data:image/png;base64,AAAA" : null,
        };
    }
    return menus;
}

/**
 * 挂载首页. 应用启动时的请求 (翻译, l10n 等) 仍走真实的 fetch, 否则 l10n 参数
 * 永远不会就绪, 组件挂载会一直等待
 */
async function mountHomeMenu() {
    return mountWithCleanup(HomeMenu);
}

/** 替换 browser.fetch, 只让菜单接口返回指定的菜单数据 */
function stubMenus(menus) {
    const originalFetch = browser.fetch;
    patchWithCleanup(browser, {
        fetch: (url, ...args) => {
            if (String(url).includes("/mobile_web/webclient/load_menus")) {
                return Promise.resolve({ ok: true, json: async () => menus });
            }
            return originalFetch(url, ...args);
        },
    });
}

test("menus are laid out 15 per page, one dot per page", async () => {
    stubMenus(makeMenus(32));
    await mountHomeMenu();
    expect(queryAll(".m_home_menu_page").length).toBe(3);
    expect(queryAll(".m_home_menu_dot").length).toBe(3);
    expect(queryAll(".m_home_menu_page")[0].querySelectorAll(".m_home_menu_item").length).toBe(15);
    expect(queryAll(".m_home_menu_page")[2].querySelectorAll(".m_home_menu_item").length).toBe(2);
});

test("a single page shows no page dots", async () => {
    stubMenus(makeMenus(7));
    await mountHomeMenu();
    expect(queryAll(".m_home_menu_page").length).toBe(1);
    expect(queryAll(".m_home_menu_dot").length).toBe(0);
});

test("apps without an icon get a coloured tile with their initial", async () => {
    stubMenus(makeMenus(2, { withIcon: false }));
    await mountHomeMenu();
    expect(queryAll(".m_home_menu_fallback").length).toBe(2);
    expect(queryAll(".m_home_menu_fallback")[0]).toHaveText("A");
    expect(queryAll("img.m_home_menu_icon").length).toBe(0);
});

test("apps with an icon show the icon image", async () => {
    stubMenus(makeMenus(2));
    await mountHomeMenu();
    expect(queryAll("img.m_home_menu_icon").length).toBe(2);
});

test("only menus with an action are shown", async () => {
    const menus = makeMenus(2);
    menus[3] = { id: 3, name: "Category only", actionID: false, webIconData: null };
    stubMenus(menus);
    await mountHomeMenu();
    expect(queryAll(".m_home_menu_item").length).toBe(2);
});

test("clicking an app runs its action", async () => {
    resetMobileActionCalls();
    stubMenus(makeMenus(2));
    await mountHomeMenu();
    await click(queryAll(".m_home_menu_item")[1]);
    expect(doActionCalls.map((call) => call.actionId)).toEqual(["101"]);
});

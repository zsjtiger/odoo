import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { EventBus, Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { MobileActionContainer } from "@mobile_web/layout/action_container/action_container";
import { MobileActionMenu } from "@mobile_web/actions/action_menu/action_menu";
import { mobileActionCalls, resetMobileActionCalls } from "@mobile_web/../tests/helpers/mobile_action_stub";

describe.current.tags("mobile");

/** 等待组件完成异步渲染 */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

class Stub extends Component {
    static template = xml`<div class="stub_page">Stub page</div>`;
}

test("the container shows the component of the latest action", async () => {
    const bus = new EventBus();
    await mountWithCleanup(MobileActionContainer, { componentEnv: { bus } });
    expect(queryAll(".stub_page").length).toBe(0);
    bus.trigger("ACTION_MANAGER:UPDATE", { Component: Stub, componentProps: {}, currentActions: [] });
    await settle();
    expect(queryOne(".stub_page")).toHaveText("Stub page");
});

test("the action menu lists the page's actions", async () => {
    await mountWithCleanup(MobileActionMenu, {
        props: {
            actions: [
                { name: "Partners", action_id: 11, svg_icon_href: "#a" },
                { name: "Products", action_id: 12, svg_icon_href: "#b" },
            ],
        },
    });
    const names = queryAll(".action_menu_item .action_name").map((el) => el.textContent);
    expect(names).toEqual(["Partners", "Products"]);
});

test("clicking a menu item runs its action", async () => {
    resetMobileActionCalls();
    await mountWithCleanup(MobileActionMenu, {
        props: { actions: [{ name: "Products", action_id: 12, svg_icon_href: "#b" }] },
    });
    await click(".action_menu_item");
    expect(mobileActionCalls.map((call) => call.actionId)).toEqual(["12"]);
});

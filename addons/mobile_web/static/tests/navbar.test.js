import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { MobileNavBar } from "@mobile_web/webclient/navbar/navbar";
import { mobileActionCalls, resetMobileActionCalls } from "@mobile_web/../tests/helpers/mobile_action_stub";

describe.current.tags("mobile");

/** 等待组件完成异步渲染 */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("the navbar shows the title sent on the bus", async () => {
    const bus = new EventBus();
    await mountWithCleanup(MobileNavBar, { componentEnv: { bus } });
    bus.trigger("NAVBAR_TITLE:UPDATE", { title: "Partners" });
    await settle();
    expect(queryOne(".m_navbar_title")).toHaveText("Partners");
});

test("the navbar has no back button, only the home button", async () => {
    await mountWithCleanup(MobileNavBar, { componentEnv: { bus: new EventBus() } });
    expect(queryAll(".m_navbar_back").length).toBe(0);
    expect(queryAll(".m_navbar_return_home").length).toBe(1);
});

test("the home button runs the home action", async () => {
    resetMobileActionCalls();
    await mountWithCleanup(MobileNavBar, { componentEnv: { bus: new EventBus() } });
    await click(".m_navbar_return_home");
    expect(mobileActionCalls.map((call) => call.actionId)).toEqual(["home"]);
});

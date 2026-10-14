import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne, queryAll } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { router } from "@mobile_web/core/browser/router";
import { MobileWebClient } from "@mobile_web/app/webclient";
import {
    mobileActionCalls,
    mobileActionState,
    resetMobileActionCalls,
} from "@mobile_web/../tests/helpers/mobile_action_stub";

describe.current.tags("mobile");

async function settle() {
    await new Promise((resolve) => setTimeout(resolve));
    await new Promise((resolve) => setTimeout(resolve));
}

test("opening the webclient runs the action in the URL", async () => {
    resetMobileActionCalls();
    patchWithCleanup(router, { current: { action: 5 } });
    await mountWithCleanup(MobileWebClient);
    await settle();
    expect(mobileActionCalls.map((call) => call.actionId)).toEqual([5]);
});

test("without an action in the URL the home page is opened", async () => {
    resetMobileActionCalls();
    patchWithCleanup(router, { current: {} });
    await mountWithCleanup(MobileWebClient);
    await settle();
    expect(mobileActionCalls.map((call) => call.actionId)).toEqual(["home"]);
});

test("a failing action shows the error in the webclient", async () => {
    resetMobileActionCalls();
    mobileActionState.error = "Action not found";
    patchWithCleanup(router, { current: { action: 99 } });
    await mountWithCleanup(MobileWebClient);
    await settle();
    expect(queryOne(".m_webclient > div[style]")).toHaveText("error: Action not found, actionReqeust: 99");
});

test("the navbar and the action container are rendered", async () => {
    resetMobileActionCalls();
    patchWithCleanup(router, { current: {} });
    await mountWithCleanup(MobileWebClient);
    expect(queryAll(".m_navbar").length).toBe(1);
    expect(queryAll(".m_action_manager").length).toBe(1);
});

test("ctrl-clicking a link lets the browser handle it, and other listeners are skipped", async () => {
    resetMobileActionCalls();
    patchWithCleanup(router, { current: {} });
    await mountWithCleanup(MobileWebClient);
    const link = document.createElement("a");
    link.href = "#somewhere";
    document.body.append(link);
    let bubbled = 0;
    const spy = () => bubbled++;
    window.addEventListener("click", spy);
    try {
        link.dispatchEvent(new MouseEvent("click", { ctrlKey: true, bubbles: true }));
        expect(bubbled).toBe(0);
        link.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(bubbled).toBe(1);
    } finally {
        window.removeEventListener("click", spy);
        link.remove();
    }
});

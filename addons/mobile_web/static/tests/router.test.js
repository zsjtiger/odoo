import { describe, expect, test } from "@odoo/hoot";
import { mobileStateToUrl, mobileUrlToState } from "@mobile_web/core/browser/router";

describe.current.tags("mobile");

test("an action with a record id maps to action and resId", () => {
    const state = mobileUrlToState(new URL("http://localhost/mobile_web/action-11/5"));
    expect(state.action).toBe(11);
    expect(state.resId).toBe(5);
});

test("the 'new' suffix maps to a new record", () => {
    const state = mobileUrlToState(new URL("http://localhost/mobile_web/action-11/new"));
    expect(state.action).toBe(11);
    expect(state.resId).toBe("new");
});

test("an action given by path keeps the path as a string", () => {
    const state = mobileUrlToState(new URL("http://localhost/mobile_web/action-partners"));
    expect(state.action).toBe("partners");
});

test("a model segment maps to the model", () => {
    const state = mobileUrlToState(new URL("http://localhost/mobile_web/m-res.partner"));
    expect(state.model).toBe("res.partner");
});

test("mobile states are written under /mobile_web", () => {
    const url = mobileStateToUrl({ action: 11, _isMobile: true });
    expect(url.startsWith("/mobile_web")).toBe(true);
    expect(url).toInclude("action-11");
});

test("desktop states keep the web prefix", () => {
    const url = mobileStateToUrl({ action: 11 });
    expect(url.startsWith("/odoo")).toBe(true);
});

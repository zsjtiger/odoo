import { describe, expect, test } from "@odoo/hoot";
import { registerMobileServices } from "@mobile_web/app/services";
import { mobileActionService } from "@mobile_web/actions/action_service";

describe.current.tags("mobile");

/** 一个只实现注册表接口子集的假分类 */
function fakeCategory(initial = {}) {
    const entries = { ...initial };
    return {
        entries,
        contains: (key) => key in entries,
        add: (key, value) => {
            entries[key] = value;
        },
    };
}

test("the mobile action service is registered under its name", () => {
    const category = fakeCategory();
    registerMobileServices(category);
    expect(category.entries.mobileAction).toBe(mobileActionService);
});

test("an existing registration is kept", () => {
    const existing = { start: () => ({}) };
    const category = fakeCategory({ mobileAction: existing });
    registerMobileServices(category);
    expect(category.entries.mobileAction).toBe(existing);
});

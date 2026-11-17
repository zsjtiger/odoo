import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { makeMobileActionManager } from "@mobile_web/actions/action_service";
import { patchTranslations } from "@web/../tests/_framework/translation_test_helpers";

describe.current.tags("mobile");

/** 一个假的 router, 只记录 pushState */
function makeRouter() {
    return { current: {}, pushState() {} };
}

/**
 * 构造动作管理器, 同时收集通知、打开的链接、服务端调用
 */
function setup({ orm = {}, reload = () => {} } = {}) {
    const bus = new EventBus();
    const notifications = [];
    const opened = [];
    const ormCalls = [];
    const env = {
        bus,
        services: {
            notification: { add: (message, options) => notifications.push([String(message), options]) },
            orm: {
                call: async (...args) => {
                    ormCalls.push(args);
                    return orm.result;
                },
            },
        },
    };
    const deps = {
        openUrl: (url, target) => opened.push([url, target]),
        reload: () => reload(),
    };
    const manager = makeMobileActionManager(env, makeRouter(), deps);
    return { manager, notifications, opened, ormCalls, bus };
}

test("an act_url action opens the link in a new window by default", async () => {
    const { manager, opened } = setup();
    await manager.doAction({ type: "ir.actions.act_url", url: "https://example.com", target: "new" });
    expect(opened).toEqual([["https://example.com", "_blank"]]);
});

test("an act_url action with target self opens in the current window", async () => {
    const { manager, opened } = setup();
    await manager.doAction({ type: "ir.actions.act_url", url: "/web", target: "self" });
    expect(opened).toEqual([["/web", "_self"]]);
});

test("a report action opens the pdf for the active records", async () => {
    const { manager, opened } = setup();
    await manager.doAction(
        { type: "ir.actions.report", report_name: "sale.report_invoice", report_type: "qweb-pdf" },
        { additionalContext: { active_ids: [4, 7] } }
    );
    expect(opened).toEqual([["/report/pdf/sale.report_invoice/4,7", "_blank"]]);
});

test("a html report action opens the html version", async () => {
    const { manager, opened } = setup();
    await manager.doAction(
        { type: "ir.actions.report", report_name: "x.report", report_type: "qweb-html" },
        { additionalContext: { active_ids: [1] } }
    );
    expect(opened).toEqual([["/report/html/x.report/1", "_blank"]]);
});

test("a server action runs on the server and opens the action it returns", async () => {
    const { manager, ormCalls, bus } = setup({ orm: { result: { type: "ir.actions.act_window", id: 9 } } });
    const opened = [];
    bus.addEventListener("ACTION_MANAGER:UPDATE", (ev) => opened.push(ev.detail));
    await manager.doAction({ type: "ir.actions.server", id: 12 });
    expect(ormCalls[0].slice(0, 3)).toEqual(["ir.actions.server", "run", [[12]]]);
    // 返回的 act_window 会被打开; 这里只需要确认动作管理器进入了 act_window 分支
    expect(opened.length).toBe(1);
});

test("a server action that returns nothing shows nothing and does not fail", async () => {
    const { manager, notifications, opened } = setup({ orm: { result: false } });
    await manager.doAction({ type: "ir.actions.server", id: 12 });
    expect(notifications.length).toBe(0);
    expect(opened.length).toBe(0);
});

test("the reload client action reloads the page", async () => {
    let reloaded = 0;
    const { manager } = setup({ reload: () => reloaded++ });
    await manager.doAction({ type: "ir.actions.client", tag: "reload" });
    expect(reloaded).toBe(1);
});

test("an unknown client action tag is reported to the user", async () => {
    patchTranslations({});
    const { manager, notifications } = setup();
    await manager.doAction({ type: "ir.actions.client", tag: "some_widget_tag" });
    expect(notifications.length).toBe(1);
    expect(notifications[0][0]).toInclude("some_widget_tag");
});

test("the notice for an unsupported action is a warning", async () => {
    patchTranslations({});
    const { manager, notifications } = setup();
    await manager.doAction({ type: "ir.actions.todo", id: 2 });
    expect(notifications[0][1].type).toBe("warning");
});

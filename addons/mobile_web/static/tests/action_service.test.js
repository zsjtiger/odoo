import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { defineModels, fields, makeMockServer, models, onRpc } from "@web/../tests/web_test_helpers";
import { MockServer } from "@web/../tests/_framework/mock_server/mock_server";
import { makeMobileActionManager, MobilePageNotFoundError } from "@mobile_web/webclient/actions/action_service";
import { MobileActWindowController } from "@mobile_web/views/act_window_controller";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { HomePage } from "@mobile_web/pages/home/home_page";
import "@mobile_web/pages";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
}

defineModels([Partner]);

/** 一个假的 router, 只记录 pushState */
function makeRouter() {
    const pushed = [];
    return {
        pushed,
        router: { current: {}, pushState: (state) => pushed.push(state) },
    };
}

/** 收集 env.bus 上的事件 */
function listen(bus, name) {
    const events = [];
    bus.addEventListener(name, (ev) => events.push(ev.detail));
    return events;
}

const ACT_WINDOW = {
    type: "ir.actions.act_window",
    id: 11,
    display_name: "Partners",
    res_model: "res.partner",
    views: [[false, "list"]],
    context: false,
    domain: false,
    path: false,
};

test("an act_window action opens the act window controller and the navbar title", async () => {
    const bus = new EventBus();
    const actions = listen(bus, "ACTION_MANAGER:UPDATE");
    const titles = listen(bus, "NAVBAR_TITLE:UPDATE");
    const { router, pushed } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus }, router);

    await doAction(ACT_WINDOW);

    expect(actions[0].Component).toBe(MobileActWindowController);
    expect(actions[0].componentProps.action.id).toBe(11);
    expect(titles[0].title).toBe("Partners");
    expect(pushed[0].action).toBe(11);
    expect(pushed[0]._isMobile).toBe(true);
});

test("a mobile page action opens its page component and lists the page's actions", async () => {
    onRpc("/mobile_web/page_actions/load", () => [
        { name: "Partners", action_id: 11, svg_icon_href: "#crossnow-icon-TabHome" },
    ]);
    if (!MockServer.current) {
        await makeMockServer();
    }
    const bus = new EventBus();
    const actions = listen(bus, "ACTION_MANAGER:UPDATE");
    const titles = listen(bus, "NAVBAR_TITLE:UPDATE");
    const { router } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus }, router);

    await doAction({
        type: "ir.actions.mobile_page",
        id: 1,
        binding_mobile_page: [5, "Home", PAGE_KEYS.HOME],
    });
    if (!MockServer.current) {
        await makeMockServer();
    }

    expect(actions[0].Component).toBe(mobilePageRegistry.get(PAGE_KEYS.HOME));
    expect(actions[0].Component).toBe(HomePage);
    expect(actions[0].currentActions[0].name).toBe("Partners");
    expect(titles[0].title).toBe("Home");
});

test("a mobile page without a component id is rejected", async () => {
    const { router } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus: new EventBus() }, router);
    let error = null;
    try {
        await doAction({ type: "ir.actions.mobile_page", id: 1, binding_mobile_page: [5, "Home", false] });
    } catch (e) {
        error = e;
    }
    expect(error instanceof MobilePageNotFoundError).toBe(true);
});

test("a mobile page without binding data is rejected", async () => {
    const { router } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus: new EventBus() }, router);
    let error = null;
    try {
        await doAction({ type: "ir.actions.mobile_page", id: 1, binding_mobile_page: false });
    } catch (e) {
        error = e;
    }
    expect(error instanceof MobilePageNotFoundError).toBe(true);
});

test("an action given by id is loaded from the server first", async () => {
    onRpc("/web/action/load", () => ({ ...ACT_WINDOW, help: "<p>Help</p>" }));
    if (!MockServer.current) {
        await makeMockServer();
    }
    const bus = new EventBus();
    const actions = listen(bus, "ACTION_MANAGER:UPDATE");
    const { router } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus }, router);

    await doAction(11);

    expect(actions[0].componentProps.action.res_model).toBe("res.partner");
});

test("an unsupported action type is ignored without touching the page", async () => {
    const bus = new EventBus();
    const actions = listen(bus, "ACTION_MANAGER:UPDATE");
    const { router, pushed } = makeRouter();
    const { doAction } = makeMobileActionManager({ bus }, router);

    await doAction({ type: "ir.actions.client", id: 3 });

    expect(actions.length).toBe(0);
    expect(pushed.length).toBe(0);
});

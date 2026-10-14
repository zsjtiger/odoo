import { describe, expect, test } from "@odoo/hoot";
import { defineModels, fields, makeMockServer, models, onRpc } from "@web/../tests/web_test_helpers";
import { MockServer } from "@web/../tests/_framework/mock_server/mock_server";
import { loadAction, loadPageActions } from "@mobile_web/webclient/actions/action_loader";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
}

defineModels([Partner]);

test("an action object is returned as it is, without a server call", async () => {
    const action = { type: "ir.actions.act_window", id: 3 };
    expect(await loadAction(action)).toBe(action);
});

test("an action id is loaded from /web/action/load", async () => {
    let request = null;
    onRpc("/web/action/load", async (req) => {
        request = (await req.json()).params;
        return { type: "ir.actions.act_window", id: 11, res_model: "res.partner" };
    });
    if (!MockServer.current) {
        await makeMockServer();
    }
    const action = await loadAction(11, { lang: "en_US" });
    expect(action.res_model).toBe("res.partner");
    expect(request.action_id).toBe(11);
});

test("an action's help text is marked as safe html", async () => {
    onRpc("/web/action/load", () => ({ type: "ir.actions.act_window", id: 11, help: "<p>Help</p>" }));
    if (!MockServer.current) {
        await makeMockServer();
    }
    const action = await loadAction("partners");
    expect(String(action.help)).toBe("<p>Help</p>");
    expect(typeof action.help).toBe("object");
});

test("the page actions of a mobile page are loaded by page id", async () => {
    let request = null;
    onRpc("/mobile_web/page_actions/load", async (req) => {
        request = (await req.json()).params;
        return [{ name: "Partners", action_id: 11, svg_icon_href: "#a" }];
    });
    if (!MockServer.current) {
        await makeMockServer();
    }
    const actions = await loadPageActions(5);
    expect(actions[0].action_id).toBe(11);
    expect(request.mobile_page_id).toBe(5);
});

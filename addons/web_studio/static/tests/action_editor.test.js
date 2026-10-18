import { describe, expect, test, waitFor } from "@odoo/hoot";
import { edit, press } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    mountWithCleanup,
    onRpc,
    getService,
    models,
    fields,
    defineModels,
    defineActions,
} from "@web/../tests/web_test_helpers";
import { WebClientEnterprise } from "@web_enterprise/webclient/webclient";
import { defineStudioEnvironment } from "./studio_tests_context";
import { openApp, openStudioHome } from "./studio_test_navigation";

describe.current.tags("desktop");

defineStudioEnvironment();

test("create unavailable view", async () => {
    expect.assertions(1);
    await mountWithCleanup(WebClientEnterprise);
    await animationFrame();

    await openStudioHome();
    await openApp("app_1");
    await contains(".o_menu_sections button:contains(Views)").click();
    await contains(".o_web_studio_thumbnail_item.o_web_studio_thumbnail_activity").click();

    expect(".o_notification_content").toHaveText("Activity view unavailable on this model");
});

test("disable the view from studio", async () => {
    let listIsDisabled = false;

    onRpc("/web_studio/edit_action", async () => {
        listIsDisabled = true;
        return true;
    });

    onRpc("/web/action/load", async () => {
        if (listIsDisabled) {
            return {
                id: 1,
                name: "partner Action (kanban first)",
                res_model: "partner",
                type: "ir.actions.act_window",
                xml_id: "partner_action_1",
                view_mode: "kanban",
                views: [
                    [1, "kanban"],
                    [false, "search"],
                    [false, "form"],
                ],
                group_ids: [],
            };
        }
    });

    await mountWithCleanup(WebClientEnterprise);
    await animationFrame();

    await openStudioHome();
    await openApp("app_1");
    await contains(".o_menu_sections button:contains(Views)").click();
    await contains(".o_web_studio_thumbnail_list .o_web_studio_more").click();
    await contains(".o-dropdown-item:contains('Disable View')").click();

    expect(".o_web_studio_thumbnail_list.disabled").toHaveCount(1);

    await contains(".o_web_studio_thumbnail_kanban .o_web_studio_more").click();
    await contains(".o-dropdown-item:contains('Disable View')").click();

    expect(".o_technical_modal .modal-body").toHaveText(
        "You cannot deactivate this view as it is the last one active."
    );
});

test("add groups on action", async () => {
    onRpc("/web_studio/edit_action", async (request) => {
        const { params } = await request.json();
        expect(params.args.group_ids[0]).toEqual([4, 11]);
    });

    await mountWithCleanup(WebClientEnterprise);
    await animationFrame();

    await openStudioHome();
    await openApp("app_1");
    await contains(".o_menu_sections button:contains(Views)").click();

    await contains("input#group_ids").click();
    await contains(".o-autocomplete--dropdown-item .dropdown-item:nth-child(1)").click();
});

test("concurrency: keep user's input when editing action", async () => {
    const def = Promise.withResolvers();
    let actionName = "Partner View";
    onRpc("/web_studio/edit_action", async (request) => {
        const { params } = await request.json();
        expect(params.args).toEqual({ name: "testInput" });
        expect.step("edit_action");
        actionName = params.args.name;
        await def.promise;
    });
    onRpc("/web/action/load", async (request) => {
        const { params } = await request.json();
        if (params.action_id !== 1) {
            // Other actions (e.g. the Studio home) are handled by the default mock server
            return;
        }
        expect.step("load_action");
        return {
            id: 1,
            name: actionName,
            res_model: "partner",
            type: "ir.actions.act_window",
            xml_id: "partner_action_1",
            view_mode: "kanban",
            views: [
                [1, "kanban"],
                [2, "list"],
                [false, "search"],
                [false, "form"],
            ],
            group_ids: [],
        };
    });

    await mountWithCleanup(WebClientEnterprise);
    await animationFrame();

    await openStudioHome();
    await openApp("app_1");
    await contains(".o_menu_sections button:contains(Views)").click();
    expect.verifySteps(["load_action"]);

    await contains(".o_web_studio_sidebar_content input#name").click();
    await edit("testInput");
    await animationFrame();
    await contains(".o_web_studio_sidebar_content textarea#help").click();
    await edit("<p>test help</p>");

    def.resolve();
    await def.promise;
    await animationFrame();

    expect.verifySteps(["edit_action", "load_action"]);
    expect(".o_web_studio_sidebar_content input#name").toHaveValue("testInput");
    expect(".o_web_studio_sidebar_content textarea#help").toHaveValue("<p>test help</p>");
});

test("active_id and active_ids present in context at reload", async () => {
    onRpc("/web_studio/edit_action", async () => {
        expect.step("edit_action");
    });
    onRpc("/web/action/load", async (request) => {
        const { params } = await request.json();
        expect.step(`load_action: ${JSON.stringify(params)}`);
    });

    await mountWithCleanup(WebClientEnterprise);
    await animationFrame();

    await openApp("app_1");
    await animationFrame();
    expect.verifySteps([
        `load_action: {"action_id":1,"context":{"lang":"en","tz":"taht","uid":7,"allowed_company_ids":[1]}}`,
    ]);

    await contains(".o_web_studio_navbar_item").click();
    await contains(".o_menu_sections button:contains(Views)").click();

    await contains(".o_web_studio_sidebar_content input#name").click();
    await edit("testInput");
    await animationFrame();
    await press("Tab");
    await animationFrame();

    expect.verifySteps([
        "edit_action",
        `load_action: {"action_id":1,"context":{"lang":"en","tz":"taht","uid":7,"allowed_company_ids":[1]}}`,
    ]);
});


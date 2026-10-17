import { describe, expect, test, beforeEach } from "@odoo/hoot";
import { queryAllTexts, waitUntil } from "@odoo/hoot-dom";
import { EventBus } from "@odoo/owl";
import { contains, defineActions, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/framework/registry";
import { ModelDesigner } from "@web_studio/client_action/model_designer/model_designer";
import { defineStudioEnvironment } from "./studio_tests_context";

describe.current.tags("desktop");

defineStudioEnvironment();

const setParamsCalls = [];
const studioService = {
    start() {
        return {
            MODES: { EDITOR: "editor" },
            bus: new EventBus(),
            editedAction: null,
            editedViewType: null,
            editorTab: "models",
            setParams(params) {
                setParamsCalls.push(params);
            },
        };
    },
};
registry.category("services").add("studio", studioService, { force: true });

const irModels = [
    { id: 1, name: "Contact", model: "partner", state: "base" },
    { id: 2, name: "Ticket", model: "x_ticket", state: "manual" },
];

defineActions([
    { id: 501, name: "Contacts", res_model: "partner", type: "ir.actions.act_window", views: [[false, "list"], [false, "form"]] },
]);

beforeEach(() => {
    setParamsCalls.length = 0;
    onRpc("ir.model", "search_read", () => irModels);
    onRpc("ir.actions.act_window", "search_read", () => [
        { id: 501, res_model: "partner", view_mode: "list,form" },
    ]);
});

const mountDesigner = () =>
    mountWithCleanup(ModelDesigner, {
        props: { action: {}, actionId: 1, className: "", updateActionState() {} },
    });

test("lists models with their type and layouts", async () => {
    await mountDesigner();
    expect(".o_web_studio_model_row").toHaveCount(2);
    expect(queryAllTexts(".o_web_studio_model_name")).toEqual(["Contact", "Ticket"]);
    expect(queryAllTexts(".o_web_studio_model_row .badge")).toEqual([
        "Standard",
        "List",
        "Form",
        "Custom",
    ]);
});

test("search filters models by name or technical name", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_search").edit("x_tick");
    expect(queryAllTexts(".o_web_studio_model_name")).toEqual(["Ticket"]);
});

test("type filter shows only custom models", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_designer .btn-group button:contains(Custom)").click();
    expect(queryAllTexts(".o_web_studio_model_name")).toEqual(["Ticket"]);
});

test("opens the form layout of a model with an action in the view editor", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_row:contains(Contact) .o_web_studio_open_form").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.editorTab).toBe("views");
    expect(params.viewType).toBe("form");
    expect(params.action.id).toBe(501);
});

test("opens a model without action with a default list action", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_row:contains(Ticket) .o_web_studio_open_list").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.viewType).toBe("list");
    expect(params.action.res_model).toBe("x_ticket");
    expect(params.action.views).toEqual([[false, "list"]]);
});

test("shows an empty state when no model matches", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_search").edit("zzz");
    expect(".o_web_studio_model_empty").toHaveCount(1);
});

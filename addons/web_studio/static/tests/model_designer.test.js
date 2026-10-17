import { describe, expect, test, beforeEach } from "@odoo/hoot";
import { queryAllTexts, waitUntil } from "@odoo/hoot-dom";
import { EventBus } from "@odoo/owl";
import { contains, defineActions, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/framework/registry";
import { ModelDesigner } from "@web_studio/client_action/model_designer/model_designer";
import { designerState } from "@web_studio/client_action/model_designer/designer_state";
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

const irFields = {
    partner: [
        { id: 10, name: "name", field_description: "Name", ttype: "char", required: true, state: "base" },
        { id: 11, name: "x_loyalty", field_description: "Loyalty", ttype: "integer", required: false, state: "manual" },
    ],
    x_ticket: [
        { id: 20, name: "x_title", field_description: "Title", ttype: "char", required: false, state: "manual" },
    ],
};

defineActions([
    { id: 501, name: "Contacts", res_model: "partner", type: "ir.actions.act_window", views: [[false, "list"], [false, "form"]] },
]);

let createdValues = null;

beforeEach(() => {
    designerState.selectedModelId = null;
    designerState.section = "fields";
    setParamsCalls.length = 0;
    createdValues = null;
    onRpc("ir.model", "search_read", () => irModels);
    onRpc("ir.actions.act_window", "search_read", () => [
        { id: 501, res_model: "partner", view_mode: "list,form" },
    ]);
    onRpc("ir.model.fields", "search_read", ({ kwargs }) => irFields[kwargs.domain[0][2]] || []);
    onRpc("ir.model.fields", "create", ({ args, kwargs }) => {
        createdValues = { values: args[0][0], context: kwargs.context };
        irFields.x_ticket.push({ id: 99, name: args[0][0].name, field_description: args[0][0].field_description, ttype: args[0][0].ttype, required: false, state: "manual" });
        return [99];
    });
});

const mountDesigner = () =>
    mountWithCleanup(ModelDesigner, {
        props: { action: {}, actionId: 1, className: "", updateActionState() {} },
    });

test("lists models with their type and page layouts", async () => {
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

test("clicking a model opens its detail with the fields", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Contact)").click();
    expect(".o_web_studio_model_detail_title").toHaveText("Contact");
    expect(".o_web_studio_model_row").toHaveCount(0);
    expect(queryAllTexts(".o_web_studio_field_row td:nth-child(1)")).toEqual(["Name", "Loyalty"]);
});

test("the Page Layouts section lists the views of the model", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Contact)").click();
    await contains(".o_web_studio_model_section:contains(Page Layouts)").click();
    expect(queryAllTexts(".o_web_studio_layout_card .card-title")).toEqual(["Form", "List"]);
});

test("editing a layout opens the matching view in the view editor", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Contact)").click();
    await contains(".o_web_studio_model_section:contains(Page Layouts)").click();
    await contains(".o_web_studio_edit_layout[data-view-type=form]").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.editorTab).toBe("views");
    expect(params.viewType).toBe("form");
    expect(params.action.id).toBe(501);
});

test("a model without action gets a default action for its layout", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Ticket)").click();
    await contains(".o_web_studio_model_section:contains(Page Layouts)").click();
    await contains(".o_web_studio_edit_layout[data-view-type=list]").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.viewType).toBe("list");
    expect(params.action.res_model).toBe("x_ticket");
    expect(params.action.views).toEqual([[false, "list"]]);
});

test("creating a field from the detail adds it to the model", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Ticket)").click();
    await contains(".o_web_studio_new_field").click();
    await contains("#o_web_studio_new_field_label").edit("Loyalty level");
    expect("#o_web_studio_new_field_name").toHaveValue("x_loyalty_level");
    await contains(".o_web_studio_create_field").click();
    await waitUntil(() => createdValues);
    expect(createdValues.values).toEqual({
        model_id: 2,
        name: "x_loyalty_level",
        field_description: "Loyalty level",
        ttype: "char",
    });
    expect(createdValues.context.studio).toBe(true);
    await waitUntil(() => queryAllTexts(".o_web_studio_field_row td:nth-child(1)").includes("Loyalty level"));
});

test("going back to the list from the detail", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Contact)").click();
    await contains(".o_web_studio_model_back").click();
    expect(".o_web_studio_model_row").toHaveCount(2);
});

test("shows an empty state when no model matches", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_search").edit("zzz");
    expect(".o_web_studio_model_empty").toHaveCount(1);
});

import { describe, expect, test, beforeEach } from "@odoo/hoot";
import { queryAllTexts, queryOne, waitUntil } from "@odoo/hoot-dom";
import { EventBus } from "@odoo/owl";
import { contains, defineActions, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/framework/registry";
import { ModelDesigner } from "@web_studio/client_action/model_designer/model_designer";
import { designerState } from "@web_studio/client_action/model_designer/designer_state";
import {
    labelToOptionValue,
} from "@web_studio/client_action/model_designer/model_detail/field_detail_page";
import {
    labelToFieldName,
    parsePicklistValues,
    relationTableName,
} from "@web_studio/client_action/model_designer/model_detail/new_field_dialog";
import { urlButtonCode } from "@web_studio/client_action/model_designer/model_detail/model_buttons";
import { defineStudioEnvironment } from "./studio_tests_context";

describe.current.tags("desktop");

defineStudioEnvironment();

const setParamsCalls = [];
const studioService = {
    start() {
        return {
            MODES: { EDITOR: "editor", MODELS: "models", HOME_MENU: "home_menu" },
            bus: new EventBus(),
            editedAction: null,
            editedViewType: null,
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

const defaultFields = () => ({
    partner: [
        { id: 10, name: "name", field_description: "Name", help: "", ttype: "char", required: true, relation: false, relation_table: false, state: "base", selection_ids: [] },
        { id: 11, name: "x_loyalty", field_description: "Loyalty", help: "", ttype: "integer", required: false, relation: false, relation_table: false, state: "manual", selection_ids: [] },
        { id: 12, name: "x_stage", field_description: "Stage", help: "", ttype: "selection", required: false, relation: false, relation_table: false, state: "manual", selection_ids: [71, 72] },
    ],
    x_ticket: [
        { id: 20, name: "x_title", field_description: "Title", help: "", ttype: "char", required: false, relation: false, relation_table: false, state: "manual", selection_ids: [] },
    ],
});

const defaultSelections = () => [
    { id: 71, value: "new", name: "New", sequence: 1 },
    { id: 72, value: "done", name: "Done", sequence: 2 },
];

defineActions([
    { id: 501, name: "Contacts", res_model: "partner", type: "ir.actions.act_window", views: [[false, "list"], [false, "form"]] },
]);

let irFields;
let irSelections;
let irServerActions;
let calls;

beforeEach(() => {
    designerState.selectedModelId = null;
    designerState.selectedModel = null;
    designerState.section = "fields";
    designerState.selectedFieldId = null;
    setParamsCalls.length = 0;
    irFields = defaultFields();
    irSelections = defaultSelections();
    irServerActions = [
        { id: 300, name: "Send email", state: "code", code: "action = {}", binding_view_types: "form,list" },
        { id: 301, name: "Download (vCard)", state: "code", code: "action = {}", binding_view_types: "form,list" },
    ];
    calls = { create: [], write: [], unlink: [] };
    onRpc("ir.model", "search_read", () => irModels);
    onRpc("ir.actions.act_window", "search_read", () => [
        { id: 501, res_model: "partner", view_mode: "list,form" },
    ]);
    onRpc("ir.model.fields", "search_read", ({ kwargs }) => {
        if (kwargs.domain[0][0] === "ttype") {
            return irFields.partner.concat(irFields.x_ticket).filter((f) => f.ttype === "many2many").map((f) => ({ relation_table: f.relation_table }));
        }
        return irFields[kwargs.domain[0][2]] || [];
    });
    onRpc("ir.model.fields", "read", ({ args }) => {
        const ids = args[0];
        return Object.values(irFields)
            .flat()
            .filter((field) => ids.includes(field.id));
    });
    onRpc("ir.model.fields.selection", "read", ({ args }) => irSelections.filter((s) => args[0].includes(s.id)));
    onRpc("ir.model.fields", "create", ({ args, kwargs }) => {
        calls.create.push({ model: "ir.model.fields", values: args[0][0], context: kwargs.context });
        return [99];
    });
    onRpc("ir.model.fields", "write", ({ args, kwargs }) => {
        calls.write.push({ ids: args[0], values: args[1], context: kwargs.context });
        return true;
    });
    onRpc("ir.model.fields", "unlink", ({ args, kwargs }) => {
        calls.unlink.push({ ids: args[0], context: kwargs.context });
        return true;
    });
    onRpc("ir.actions.server", "search_read", () => irServerActions);
    onRpc("ir.actions.server", "create", ({ args, kwargs }) => {
        calls.create.push({ model: "ir.actions.server", values: args[0][0], context: kwargs.context });
        return [400];
    });
    onRpc("ir.actions.server", "unlink", ({ args, kwargs }) => {
        calls.unlink.push({ model: "ir.actions.server", ids: args[0], context: kwargs.context });
        return true;
    });
    onRpc("ir.model.data", "search_read", ({ kwargs }) => {
        // Only the vCard action comes from a module
        return kwargs.domain.some((d) => d[0] === "res_id" && d[2].includes(301)) ? [{ res_id: 301 }] : [];
    });
});

const mountDesigner = () =>
    mountWithCleanup(ModelDesigner, {
        props: { action: {}, actionId: 1, className: "", updateActionState() {} },
    });

const openContact = async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Contact)").click();
};

const openTicket = async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_name:contains(Ticket)").click();
};

const openField = async (label) => {
    await contains(`.o_web_studio_field_row:contains(${label})`).click();
};

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

test("clicking a model opens its detail with the fields", async () => {
    await openContact();
    expect(".o_web_studio_model_detail_title").toHaveText("Contact");
    expect(".o_web_studio_model_row").toHaveCount(0);
    expect(queryAllTexts(".o_web_studio_field_row td:nth-child(1)")).toEqual(["Name", "Loyalty", "Stage"]);
});

test("the type filter on fields separates standard and custom fields", async () => {
    await openContact();
    await contains(".o_web_studio_filter_custom").click();
    expect(queryAllTexts(".o_web_studio_field_row td:nth-child(1)")).toEqual(["Loyalty", "Stage"]);
});

test("editing a layout opens the matching view in the view editor", async () => {
    await openContact();
    await contains(".o_web_studio_model_section:contains(Page Layouts)").click();
    expect(queryAllTexts(".o_web_studio_layout_card .card-title")).toEqual(["Form", "List"]);
    await contains(".o_web_studio_edit_layout[data-view-type=form]").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.mode).toBe("editor");
    expect(params.viewType).toBe("form");
    expect(params.action.id).toBe(501);
});

test("a model without action gets a default action for its layout", async () => {
    await openTicket();
    await contains(".o_web_studio_model_section:contains(Page Layouts)").click();
    await contains(".o_web_studio_edit_layout[data-view-type=list]").click();
    await waitUntil(() => setParamsCalls.length === 1);
    const params = setParamsCalls.at(-1);
    expect(params.action.res_model).toBe("x_ticket");
    expect(params.action.views).toEqual([[false, "list"]]);
});

test("clicking a field opens its own page with the field properties", async () => {
    await openContact();
    await openField("Loyalty");
    expect(".o_web_studio_field_page_title").toHaveText("Loyalty");
    expect("#o_web_studio_field_page_name").toHaveValue("x_loyalty");
    expect(queryOne(".o_web_studio_field_required").disabled).toBe(false);
    expect(".o_web_studio_field_page_body").toHaveCount(1);
});

test("a standard field can be relabelled but not made required", async () => {
    await openContact();
    await openField("Name");
    expect(queryOne(".o_web_studio_field_required").disabled).toBe(true);
    expect(".o_web_studio_delete_field").toHaveCount(0);
    expect(".o_web_studio_picklist").toHaveCount(0);
});

test("saving a field label writes it with the studio context", async () => {
    await openContact();
    await openField("Loyalty");
    await contains("#o_web_studio_field_page_label").edit("Loyalty points");
    await contains(".o_web_studio_save_field").click();
    await waitUntil(() => calls.write.length === 1);
    expect(calls.write[0].ids).toEqual([11]);
    expect(calls.write[0].values).toEqual({ field_description: "Loyalty points" });
    expect(calls.write[0].context.studio).toBe(true);
});

test("deleting a custom field asks for a confirmation first", async () => {
    await openContact();
    await openField("Loyalty");
    await contains(".o_web_studio_delete_field").click();
    expect(calls.unlink).toHaveLength(0);
    await contains(".o_dialog .btn-danger").click();
    await waitUntil(() => calls.unlink.length === 1);
    expect(calls.unlink[0].ids).toEqual([11]);
    expect(calls.unlink[0].context.studio).toBe(true);
    await waitUntil(() => !document.querySelector(".o_web_studio_field_page"));
});

test("picklist values can be renamed, added, reordered and removed", async () => {
    await openContact();
    await openField("Stage");
    expect(".o_web_studio_picklist_row").toHaveCount(2);
    await contains(".o_web_studio_picklist_name").edit("Brand new");
    await contains(".o_web_studio_picklist_add").click();
    await contains(".o_web_studio_picklist_row:last-child .o_web_studio_picklist_name").edit("Third");
    await contains(".o_web_studio_picklist_row:nth-child(2) .o_web_studio_picklist_remove").click();
    await contains(".o_web_studio_save_field").click();
    await waitUntil(() => calls.write.length === 1);
    expect(calls.write[0].values.selection_ids).toEqual([
        [2, 72],
        [1, 71, { name: "Brand new", sequence: 1 }],
        [0, 0, { value: "third", name: "Third", sequence: 2 }],
    ]);
});

test("creating a field from the detail", async () => {
    await openTicket();
    await contains(".o_web_studio_new_field").click();
    await contains("#o_web_studio_new_field_label").edit("Loyalty level");
    expect("#o_web_studio_new_field_name").toHaveValue("x_loyalty_level");
    await contains(".o_web_studio_create_field").click();
    await waitUntil(() => calls.create.length === 1);
    expect(calls.create[0].values).toEqual({
        model_id: 2,
        name: "x_loyalty_level",
        field_description: "Loyalty level",
        ttype: "char",
    });
    expect(calls.create[0].context.studio).toBe(true);
});

test("creating a lookup field needs a related model", async () => {
    await openTicket();
    await contains(".o_web_studio_new_field").click();
    await contains("#o_web_studio_new_field_label").edit("Customer");
    await contains("#o_web_studio_new_field_type").select("many2one");
    expect(queryOne(".o_web_studio_create_field").disabled).toBe(true);
    await contains(".o_web_studio_new_field_relation").select("partner");
    await contains(".o_web_studio_create_field").click();
    await waitUntil(() => calls.create.length === 1);
    expect(calls.create[0].values).toMatchObject({
        name: "x_customer",
        ttype: "many2one",
        relation: "partner",
    });
});

test("creating a many2many field creates its junction table", async () => {
    await openTicket();
    await contains(".o_web_studio_new_field").click();
    await contains("#o_web_studio_new_field_label").edit("Watchers");
    await contains("#o_web_studio_new_field_type").select("many2many");
    await contains(".o_web_studio_new_field_relation").select("partner");
    await contains(".o_web_studio_create_field").click();
    await waitUntil(() => calls.create.length === 1);
    expect(calls.create[0].values).toMatchObject({
        name: "x_watchers",
        ttype: "many2many",
        relation: "partner",
        relation_table: "x_x_ticket_partner_rel",
    });
});

test("creating a picklist field stores its values", async () => {
    await openTicket();
    await contains(".o_web_studio_new_field").click();
    await contains("#o_web_studio_new_field_label").edit("Stage");
    await contains("#o_web_studio_new_field_type").select("selection");
    await contains(".o_web_studio_new_field_picklist").edit("New\nIn Progress\nNew");
    await contains(".o_web_studio_create_field").click();
    await waitUntil(() => calls.create.length === 1);
    expect(calls.create[0].values.ttype).toBe("selection");
    expect(calls.create[0].values.selection_ids).toEqual([
        [0, 0, { value: "new", name: "New", sequence: 1 }],
        [0, 0, { value: "in_progress", name: "In Progress", sequence: 2 }],
    ]);
});

test("the field list shows a button to load more fields", async () => {
    irFields.partner = Array.from({ length: 120 }, (_, index) => ({
        id: 1000 + index,
        name: `x_field_${index}`,
        field_description: `Field ${index}`,
        help: "",
        ttype: "char",
        required: false,
        relation: false,
        relation_table: false,
        state: "manual",
        selection_ids: [],
    }));
    await openContact();
    expect(".o_web_studio_field_row").toHaveCount(100);
    await contains(".o_web_studio_show_more_fields").click();
    expect(".o_web_studio_field_row").toHaveCount(120);
    expect(".o_web_studio_show_more_fields").toHaveCount(0);
});

test("the buttons section lists standard and custom buttons", async () => {
    await openContact();
    await contains(".o_web_studio_model_section:contains(Buttons)").click();
    expect(".o_web_studio_standard_button_row").toHaveCount(3);
    expect(queryAllTexts(".o_web_studio_module_button_row td:nth-child(1)")).toEqual(["Download (vCard)"]);
    expect(queryAllTexts(".o_web_studio_button_row td:nth-child(1)")).toEqual(["Send email"]);
    expect(".o_web_studio_delete_button").toHaveCount(1);
});

test("creating a button that opens a URL", async () => {
    await openTicket();
    await contains(".o_web_studio_model_section:contains(Buttons)").click();
    await contains(".o_web_studio_new_button").click();
    await contains("#o_web_studio_button_label").edit("Open site");
    await contains(".o_web_studio_button_url").edit("https://example.com/{id}");
    await contains(".o_web_studio_create_button").click();
    await waitUntil(() => calls.create.length === 1);
    const values = calls.create[0].values;
    expect(calls.create[0].model).toBe("ir.actions.server");
    expect(values).toMatchObject({
        name: "Open site",
        binding_model_id: 2,
        binding_type: "action",
        binding_view_types: "form,list",
        state: "code",
    });
    expect(values.code.includes("ir.actions.act_url")).toBe(true);
});

test("deleting a custom button asks for a confirmation", async () => {
    await openContact();
    await contains(".o_web_studio_model_section:contains(Buttons)").click();
    await contains(".o_web_studio_delete_button").click();
    await contains(".o_dialog .btn-danger").click();
    await waitUntil(() => calls.unlink.length === 1);
    expect(calls.unlink[0].model).toBe("ir.actions.server");
    expect(calls.unlink[0].ids).toEqual([300]);
});

test("going back to the list from the detail", async () => {
    await openContact();
    await contains(".o_web_studio_model_back").click();
    expect(".o_web_studio_model_row").toHaveCount(2);
});

test("shows an empty state when no model matches", async () => {
    await mountDesigner();
    await contains(".o_web_studio_model_search").edit("zzz");
    expect(".o_web_studio_model_empty").toHaveCount(1);
});

test("picklist values are trimmed, deduplicated and given technical values", () => {
    expect(parsePicklistValues(" New \n\nIn Progress\nNew\n")).toEqual([
        { value: "new", name: "New" },
        { value: "in_progress", name: "In Progress" },
    ]);
    expect(labelToOptionValue("New", ["new"])).toBe("new_2");
});

test("field names are derived from labels with the custom prefix", () => {
    expect(labelToFieldName("Loyalty level")).toBe("x_loyalty_level");
    expect(labelToFieldName("  Éco & taxes!  ")).toBe("x_eco_taxes");
    expect(labelToFieldName("   ")).toBe("");
});

test("junction table names are unique", () => {
    expect(relationTableName("x_ticket", "partner", [])).toBe("x_x_ticket_partner_rel");
    expect(relationTableName("x_ticket", "partner", ["x_x_ticket_partner_rel"])).toBe(
        "x_x_ticket_partner_rel_2"
    );
});

test("URL buttons build a server action that replaces the record id", () => {
    const code = urlButtonCode("https://example.com/{id}");
    expect(code.includes('url = "https://example.com/{id}"')).toBe(true);
    expect(code.includes('"type": "ir.actions.act_url"')).toBe(true);
});

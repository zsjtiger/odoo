import { describe, expect, test, beforeEach } from "@odoo/hoot";
import { click, queryAllTexts, queryOne, waitUntil } from "@odoo/hoot-dom";
import { contains, defineModels, fields, models, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import {
    addField,
    addHeaderButton,
    addSection,
    fieldsInLayout,
    headerButtonNames,
    moveField,
    parseFormArch,
    removeItem,
    removeSection,
    replaceRootArch,
    serializeFormLayout,
    setColumnCount,
} from "@web_studio/client_action/model_designer/page_layout/page_layout_model";
import {
    parseFormArch as parseArch,
    rawItems,
    rawXml,
    setRawXml,
} from "@web_studio/client_action/model_designer/page_layout/page_layout_model";
import { PageLayoutEditor } from "@web_studio/client_action/model_designer/page_layout/page_layout_editor";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";

describe.current.tags("desktop");

const FORM_ARCH = `<form string="Contact" js_class="x">
  <header>
    <button type="object" name="action_confirm" string="Confirm"/>
  </header>
  <sheet>
    <group string="Main">
      <group>
        <field name="name"/>
        <field name="email"/>
      </group>
      <group>
        <field name="phone" widget="phone"/>
      </group>
    </group>
    <group>
      <field name="x_stage"/>
    </group>
  </sheet>
  <div class="oe_chatter"/>
</form>`;

test("parsing and serializing a form keeps its structure", () => {
    const layout = parseFormArch(FORM_ARCH);
    expect(layout.rootTag).toBe("form");
    expect(layout.rootAttributes.string).toBe("Contact");
    expect(layout.header).toHaveLength(1);
    expect(layout.header[0].kind).toBe("raw");
    expect(layout.body).toHaveLength(2);
    expect(layout.body[0].title).toBe("Main");
    expect(layout.body[0].columns).toHaveLength(2);
    expect(layout.body[1].title).toBe("");
    expect(layout.body[1].columns).toHaveLength(1);
    expect(layout.footer).toHaveLength(1);

    const serialized = serializeFormLayout(layout);
    expect(serialized.includes('string="Main"')).toBe(true);
    expect(serialized.includes('widget="phone"')).toBe(true);
    expect(serialized.includes('class="oe_chatter"')).toBe(true);
    expect(fieldsInLayout(layout)).toEqual(new Set(["name", "email", "phone", "x_stage"]));
    // Parsing what was serialized gives the same arch
    expect(serializeFormLayout(parseFormArch(serialized))).toBe(serialized);
});

test("fields can be added once, moved between sections and removed", () => {
    const layout = parseFormArch(FORM_ARCH);
    const main = layout.body[0];
    const [left, right] = main.columns;

    expect(addField(layout, main.id, left.id, "name")).toBe(false);
    expect(addField(layout, main.id, left.id, "website")).toBe(true);
    expect(left.items.at(-1).name).toBe("website");

    // Move "email" (index 1 of left) to the top of the right column
    moveField(
        layout,
        { sectionId: main.id, columnId: left.id, index: 1 },
        { sectionId: main.id, columnId: right.id, index: 0 }
    );
    expect(right.items[0].name).toBe("email");
    expect(left.items.map((item) => item.name)).toEqual(["name", "website"]);

    removeItem(layout, { sectionId: main.id, columnId: right.id, index: 0 });
    expect(fieldsInLayout(layout).has("email")).toBe(false);
});

test("moving a field inside its column keeps the order", () => {
    const layout = parseFormArch(FORM_ARCH);
    const [left] = layout.body[0].columns;
    moveField(
        layout,
        { sectionId: layout.body[0].id, columnId: left.id, index: 0 },
        { sectionId: layout.body[0].id, columnId: left.id, index: 2 }
    );
    expect(left.items.map((item) => item.name)).toEqual(["email", "name"]);
});

test("sections can be added, changed to one column and removed", () => {
    const layout = parseFormArch(FORM_ARCH);
    const section = addSection(layout, "Extra");
    expect(section.columns).toHaveLength(2);
    expect(layout.body).toHaveLength(3);

    const main = layout.body[0];
    setColumnCount(main, 1);
    expect(main.columns).toHaveLength(1);
    // The fields of the removed column stay in the layout
    expect(main.columns[0].items.map((item) => item.name)).toEqual(["name", "email", "phone"]);

    removeSection(layout, main.id);
    expect(layout.body.find((entry) => entry.id === main.id)).toBe(undefined);
    expect(fieldsInLayout(layout).has("phone")).toBe(true);
});

test("header buttons are added once and written as action buttons", () => {
    const layout = parseFormArch(FORM_ARCH);
    expect(addHeaderButton(layout, "studio_customization.studio_button_7", "Send email")).toBe(true);
    expect(addHeaderButton(layout, "studio_customization.studio_button_7", "Send email")).toBe(false);
    expect(headerButtonNames(layout)).toEqual(["studio_customization.studio_button_7"]);
    const serialized = serializeFormLayout(layout);
    expect(serialized.includes('<button type="action" name="studio_customization.studio_button_7" string="Send email"/>')).toBe(true);
});

test("the saved arch replaces the root of the form", () => {
    const arch = serializeFormLayout(parseFormArch(FORM_ARCH));
    const studioArch = replaceRootArch(arch, "form");
    expect(studioArch.startsWith('<data><xpath expr="/form" position="replace"><form')).toBe(true);
    expect(studioArch.endsWith("</form></xpath></data>")).toBe(true);
});

test("a list view is a single flat section of fields", () => {
    const layout = parseArch('<list><header><button type="action" name="a.b" string="Go"/></header><field name="name"/><field name="email"/></list>');
    expect(layout.rootTag).toBe("list");
    expect(layout.body).toHaveLength(1);
    expect(layout.body[0].flat).toBe(true);
    expect(layout.body[0].columns[0].items.map((item) => item.name)).toEqual(["name", "email"]);
    const serialized = serializeFormLayout(layout);
    expect(serialized.startsWith("<list>")).toBe(true);
    expect(serialized.includes("<group")).toBe(false);
    expect(serializeFormLayout(parseArch(serialized))).toBe(serialized);
});

test("attributes computed by the server are not kept in the arch", () => {
    const layout = parseArch(
        '<list><field name="company_id" column_invisible="True" actual_invisible="False" studio_groups="[]" data-used-by="x"/></list>'
    );
    const serialized = serializeFormLayout(layout);
    expect(serialized.includes("actual_invisible")).toBe(false);
    expect(serialized.includes("studio_groups")).toBe(false);
    expect(serialized.includes("data-used-by")).toBe(false);
    expect(serialized.includes('column_invisible="True"')).toBe(true);
});

test("the card of a kanban view is laid out as a flat section", () => {
    const arch = `<kanban sample="1">
        <field name="active"/>
        <templates>
            <t t-name="card" class="o_card">
                <field name="name"/>
                <div class="o_extra"><field name="email"/></div>
            </t>
        </templates>
    </kanban>`;
    const layout = parseArch(arch);
    expect(layout.rootTag).toBe("kanban");
    expect(layout.body[0].flat).toBe(true);
    const fieldNames = layout.body[0].columns[0].items
        .filter((item) => item.kind === "field")
        .map((item) => item.name);
    expect(fieldNames).toEqual(["name"]);
    const serialized = serializeFormLayout(layout);
    expect(serialized.includes('<t t-name="card" class="o_card">')).toBe(true);
    expect(serialized.includes('name="active"')).toBe(true);
    expect(serializeFormLayout(parseArch(serialized))).toBe(serialized);
    // The fields of the card are the ones the editor manages
    addField(layout, layout.body[0].id, layout.body[0].columns[0].id, "phone");
    expect(serializeFormLayout(layout).includes('<field name="phone"/>')).toBe(true);
});

test("advanced blocks are kept and their XML can be replaced", () => {
    const layout = parseFormArch(FORM_ARCH);
    const chatter = rawItems(layout).find((item) => item.node.getAttribute("class") === "oe_chatter");
    expect(rawXml(chatter)).toBe('<div class="oe_chatter"/>');
    setRawXml(layout, chatter.id, '<div class="oe_chatter" data-x="1"/>');
    expect(serializeFormLayout(layout).includes('data-x="1"')).toBe(true);
    expect(() => setRawXml(layout, chatter.id, "<div")).toThrow();
});

describe("page layout editor", () => {
    let saved;

    beforeEach(() => {
        saved = null;
        defineMailModels();
        defineModels([
            class Partner extends models.Model {
                _name = "partner";
                name = fields.Char();
                email = fields.Char();
                phone = fields.Char();
                website = fields.Char();
                x_stage = fields.Char();
            },
        ]);
        onRpc("/web_studio/get_studio_view_arch", () => ({
            main_view_id: 42,
            studio_view_id: false,
            studio_view_arch: "<data/>",
        }));
        onRpc("partner", "get_views", () => ({ views: { form: { arch: FORM_ARCH } } }));
        onRpc("ir.model.fields", "search_read", () => [
            { name: "name", field_description: "Name", ttype: "char", state: "base" },
            { name: "email", field_description: "Email", ttype: "char", state: "base" },
            { name: "phone", field_description: "Phone", ttype: "char", state: "base" },
            { name: "website", field_description: "Website", ttype: "char", state: "base" },
            { name: "x_stage", field_description: "Stage", ttype: "char", state: "manual" },
        ]);
        onRpc("ir.actions.server", "search_read", () => [{ id: 7, name: "Send email" }]);
        onRpc("ir.model.data", "search_read", () => []);
        onRpc("ir.model.data", "create", () => [70]);
        onRpc("/web_studio/edit_page_layout", async (request) => {
            const { params } = await request.json();
            saved = params;
            return {};
        });
    });

    const mountEditor = () =>
        mountWithCleanup(PageLayoutEditor, {
            props: {
                model: { id: 1, model: "partner", name: "Contact" },
                onAdvanced() {},
                onBack() {},
            },
        });

    test("shows the sections, the header and the palette", async () => {
        await mountEditor();
        expect(".o_web_studio_layout_section").toHaveCount(2);
        expect(queryAllTexts(".o_web_studio_layout_field .text-truncate")).toEqual([
            "Name",
            "Email",
            "Phone",
            "Stage",
        ]);
        expect(queryAllTexts(".o_web_studio_palette_field .text-truncate")).toEqual(["Website"]);
        expect(queryAllTexts(".o_web_studio_palette_button .text-truncate")).toEqual(["Send email"]);
    });

    test("adding a field from the palette and saving the layout", async () => {
        await mountEditor();
        await contains(".o_web_studio_palette_field:contains(Website) .o_web_studio_palette_add_field").click();
        expect(".o_web_studio_layout_field:contains(Website)").toHaveCount(1);
        await contains(".o_web_studio_save_layout").click();
        await waitUntil(() => saved);
        expect(saved.view_id).toBe(42);
        expect(saved.arch.includes('<xpath expr="/form" position="replace">')).toBe(true);
        expect(saved.arch.includes('name="website"')).toBe(true);
    });

    test("removing a field and changing the title of a section", async () => {
        await mountEditor();
        await contains(".o_web_studio_layout_field:contains(Email) .o_web_studio_field_remove").click();
        expect(".o_web_studio_layout_field:contains(Email)").toHaveCount(0);
        await contains(".o_web_studio_section_title").edit("Contact details");
        await contains(".o_web_studio_save_layout").click();
        await waitUntil(() => saved);
        expect(saved.arch.includes('string="Contact details"')).toBe(true);
        expect(saved.arch.includes('name="email"')).toBe(false);
    });

    test("a list layout has no section controls and saves the list arch", async () => {
        onRpc("partner", "get_views", () => ({ views: { list: { arch: '<list><field name="name"/></list>' } } }));
        await mountWithCleanup(PageLayoutEditor, {
            props: {
                model: { id: 1, model: "partner", name: "Contact" },
                viewType: "list",
                onAdvanced() {},
                onBack() {},
            },
        });
        expect(".o_web_studio_section_title").toHaveCount(0);
        expect(".o_web_studio_add_section").toHaveCount(0);
        await contains(".o_web_studio_palette_field:contains(Email) .o_web_studio_palette_add_field").click();
        await contains(".o_web_studio_save_layout").click();
        await waitUntil(() => saved);
        expect(saved.arch.startsWith('<data><xpath expr="/list" position="replace"><list>')).toBe(true);
        expect(saved.arch.includes('name="email"')).toBe(true);
    });

    test("an advanced block can be edited as XML", async () => {
        await mountEditor();
        await click(queryOne(".o_web_studio_raw_edit"));
        await contains(".o_web_studio_raw_draft").edit('<div class="oe_edited"/>');
        await contains(".o_web_studio_raw_apply").click();
        expect(queryOne(".o_web_studio_save_layout").disabled).toBe(false);
        await contains(".o_web_studio_save_layout").click();
        await waitUntil(() => saved);
        expect(saved.arch.includes('class="oe_edited"')).toBe(true);
    });

    test("a header button is added by clicking the palette and saved", async () => {
        await mountEditor();
        await contains(".o_web_studio_palette_button .o_web_studio_palette_add_button").click();
        await waitUntil(() => queryAllTexts(".o_web_studio_header_button").length === 1);
        await contains(".o_web_studio_save_layout").click();
        await waitUntil(() => saved);
        expect(saved.arch.includes('name="studio_customization.studio_button_7"')).toBe(true);
    });

    test("the palette groups the fields not in the layout into custom and standard", async () => {
        onRpc("ir.model.fields", "search_read", () => [
            { name: "name", field_description: "Name", ttype: "char", state: "base" },
            { name: "website", field_description: "Website", ttype: "char", state: "base" },
            { name: "x_budget", field_description: "Budget", ttype: "float", state: "manual" },
            { name: "x_stage", field_description: "Stage", ttype: "char", state: "manual" },
        ]);
        await mountEditor();
        // The titles are displayed in capitals
        expect(queryAllTexts(".o_web_studio_palette_group_title")).toEqual([
            "CUSTOM FIELDS",
            "STANDARD FIELDS",
        ]);
        expect(queryAllTexts(".o_web_studio_palette_field .text-truncate")).toEqual([
            "Budget",
            "Website",
        ]);
    });
});

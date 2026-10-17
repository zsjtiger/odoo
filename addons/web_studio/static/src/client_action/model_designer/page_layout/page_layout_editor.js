import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { RawBlock } from "./page_layout_raw_block";
import { rpc } from "@web/core/services/network/rpc";
import { useService } from "@web/core/utils/hooks";
import {
    STUDIO_MODULE,
    addField,
    addHeaderButton,
    addSection,
    fieldsInLayout,
    findSection,
    headerButtonNames,
    moveField,
    parseFormArch,
    rawXml,
    removeHeaderButton,
    removeItem,
    removeSection,
    replaceRootArch,
    serializeFormLayout,
    setColumnCount,
    setRawXml,
} from "./page_layout_model";

/** Fields that are always there and never placed by hand. */
const SYSTEM_FIELDS = new Set([
    "id",
    "display_name",
    "create_date",
    "create_uid",
    "write_date",
    "write_uid",
    "__last_update",
]);

function readPayload(ev) {
    try {
        return JSON.parse(ev.dataTransfer.getData("text/plain"));
    } catch {
        return null;
    }
}

/**
 * Page layout editor of a form, the way Salesforce's page layout editor works:
 * the fields and buttons are dragged from the palette to the sections and the
 * header, and the layout is saved as a whole.
 */
export class PageLayoutEditor extends Component {
    static template = "web_studio.PageLayoutEditor";
    static components = { RawBlock };

    props = useProps({
        model: t.object(),
        viewType: t.string().optional("form"),
        onAdvanced: t.function(),
        onBack: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = proxy({
            loading: true,
            saving: false,
            search: "",
            activeSectionId: null,
            editingRawId: null,
            rawDraft: "",
            showAdvanced: false,
            viewId: false,
            studioViewId: false,
            layout: null,
            initialArch: "",
            fields: [],
            buttons: [],
        });

        this.fieldsByName = computed(() =>
            Object.fromEntries(this.state.fields.map((field) => [field.name, field]))
        );

        this.paletteFields = computed(() => {
            const inLayout = fieldsInLayout(this.state.layout || { body: [] });
            const search = this.state.search.trim().toLowerCase();
            return this.state.fields.filter(
                (field) =>
                    !inLayout.has(field.name) &&
                    !SYSTEM_FIELDS.has(field.name) &&
                    (!search ||
                        field.label.toLowerCase().includes(search) ||
                        field.name.toLowerCase().includes(search))
            );
        });

        this.paletteButtons = computed(() => {
            const inHeader = this.state.layout ? headerButtonNames(this.state.layout) : [];
            return this.state.buttons.filter(
                (button) => !button.xmlid || !inHeader.includes(button.xmlid)
            );
        });

        this.isDirty = computed(
            () =>
                Boolean(this.state.layout) &&
                serializeFormLayout(this.state.layout) !== this.state.initialArch
        );

        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.state.loading = true;
                return this.load(nextProps.model);
            }
        });
    }

    async load(model = this.props.model) {
        this.state.loading = true;
        const viewType = this.props.viewType;
        const info = await rpc("/web_studio/get_studio_view_arch", {
            model: model.model,
            view_type: viewType,
        });
        const views = await this.orm.call(model.model, "get_views", [[[info.main_view_id, viewType]]], {
            context: { studio: true },
        });
        const arch = views.views[viewType].arch;
        const layout = parseFormArch(arch);
        this.state.viewId = info.main_view_id;
        this.state.studioViewId = info.studio_view_id || false;
        this.state.layout = layout;
        this.state.initialArch = serializeFormLayout(layout);
        this.state.fields = await this.loadFields(model);
        this.state.buttons = await this.loadButtons(model);
        this.state.loading = false;
    }

    async loadFields(model) {
        const fields = await this.orm.searchRead(
            "ir.model.fields",
            [["model", "=", model.model]],
            ["name", "field_description", "ttype", "state"],
            { order: "name ASC" }
        );
        return fields.map((field) => ({
            name: field.name,
            label: field.field_description,
            type: field.ttype,
            isCustom: field.state === "manual",
        }));
    }

    async loadButtons(model) {
        const actions = await this.orm.searchRead(
            "ir.actions.server",
            [
                ["binding_model_id", "=", model.id],
                ["binding_type", "=", "action"],
            ],
            ["name"],
            { order: "name ASC" }
        );
        if (!actions.length) {
            return [];
        }
        const records = await this.orm.searchRead(
            "ir.model.data",
            [
                ["model", "=", "ir.actions.server"],
                ["res_id", "in", actions.map((action) => action.id)],
            ],
            ["module", "name", "res_id"]
        );
        const xmlids = Object.fromEntries(
            records.map((record) => [record.res_id, `${record.module}.${record.name}`])
        );
        return actions.map((action) => ({
            id: action.id,
            name: action.name,
            xmlid: xmlids[action.id] || null,
        }));
    }

    /** Creates the xml id of a button, needed to reference it from the header. */
    async ensureButtonXmlid(button) {
        if (button.xmlid) {
            return button.xmlid;
        }
        const name = `studio_button_${button.id}`;
        await this.orm.create("ir.model.data", [
            { name, module: STUDIO_MODULE, model: "ir.actions.server", res_id: button.id },
        ]);
        button.xmlid = `${STUDIO_MODULE}.${name}`;
        return button.xmlid;
    }

    get headerButtons() {
        return this.state.layout.header
            .map((item, index) => ({ item, index }))
            .filter(({ item }) => item.kind === "button");
    }

    /** Label of a header button, its string or its technical name. */
    buttonLabel(node) {
        return node.getAttribute("string") || node.getAttribute("name");
    }

    fieldLabel(name) {
        return this.fieldsByName()[name]?.label || name;
    }

    // --- Palette -----------------------------------------------------------

    get paletteCustomFields() {
        return this.paletteFields().filter((field) => field.isCustom);
    }

    get paletteStandardFields() {
        return this.paletteFields().filter((field) => !field.isCustom);
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    /** The section where the palette adds fields: the active one or the first. */
    targetSection() {
        const layout = this.state.layout;
        let section = findSection(layout, this.state.activeSectionId);
        if (!section) {
            section = layout.body.find((entry) => entry.kind === "section");
        }
        if (!section) {
            section = addSection(layout, _t("Information"));
        }
        return section;
    }

    addFieldFromPalette(name) {
        const section = this.targetSection();
        addField(this.state.layout, section.id, section.columns[0].id, name);
        this.state.activeSectionId = section.id;
    }

    async addButtonFromPalette(button) {
        const xmlid = await this.ensureButtonXmlid(button);
        addHeaderButton(this.state.layout, xmlid, button.name);
    }

    onPaletteFieldDragStart(ev, field) {
        ev.dataTransfer.effectAllowed = "copy";
        ev.dataTransfer.setData("text/plain", JSON.stringify({ kind: "field", name: field.name }));
    }

    onPaletteButtonDragStart(ev, button) {
        ev.dataTransfer.effectAllowed = "copy";
        ev.dataTransfer.setData(
            "text/plain",
            JSON.stringify({ kind: "button", id: button.id, name: button.name })
        );
    }

    // --- Sections ----------------------------------------------------------

    addSection() {
        const section = addSection(this.state.layout, _t("Section %s", this.sectionCount() + 1));
        this.state.activeSectionId = section.id;
    }

    sectionCount() {
        return this.state.layout.body.filter((entry) => entry.kind === "section").length;
    }

    removeSection(section) {
        removeSection(this.state.layout, section.id);
    }

    onSectionTitle(section, ev) {
        section.title = ev.target.value;
    }

    onColumnsChange(section, ev) {
        setColumnCount(section, Number(ev.target.value));
    }

    onSectionFocus(section) {
        this.state.activeSectionId = section.id;
    }

    get viewTitle() {
        const titles = {
            form: _t("Form Page Layout"),
            list: _t("List Page Layout"),
            kanban: _t("Kanban Page Layout"),
            search: _t("Search Page Layout"),
        };
        return titles[this.props.viewType] || titles.form;
    }

    /** The layout of a list, kanban or search view has a single flat section: no title, no columns. */
    isFlat(section) {
        return Boolean(section.flat);
    }

    // --- Advanced blocks ----------------------------------------------------

    toggleAdvanced() {
        this.state.showAdvanced = !this.state.showAdvanced;
    }

    /** Number of blocks of a column that are kept as XML. */
    columnRawCount(column) {
        return column.items.filter((item) => item.kind === "raw").length;
    }

    /** Number of blocks of the layout, outside of the sections, that are kept as XML. */
    get outsideRawCount() {
        return this.state.layout.body.filter((entry) => entry.kind !== "section").length + this.state.layout.footer.length;
    }

    /** Whether the header zone applies to the view: forms and lists have a header. */
    get hasHeader() {
        return this.props.viewType === "form" || this.props.viewType === "list";
    }

    get headerHint() {
        return this.props.viewType === "list"
            ? _t("Drop a button here to show it in the header of the list.")
            : _t("Drop a button here to show it in the header of the form.");
    }

    startRawEdit(block) {
        this.state.editingRawId = block.id;
        this.state.rawDraft = rawXml(block);
    }

    onRawDraftInput(ev) {
        this.state.rawDraft = ev.target.value;
    }

    cancelRawEdit() {
        this.state.editingRawId = null;
    }

    applyRawEdit() {
        try {
            setRawXml(this.state.layout, this.state.editingRawId, this.state.rawDraft);
            this.state.editingRawId = null;
        } catch (error) {
            this.notification.add(error.message, { type: "danger" });
        }
    }

    // --- Fields in the layout -----------------------------------------------

    removeField(section, column, index) {
        removeItem(this.state.layout, { sectionId: section.id, columnId: column.id, index });
    }

    moveFieldBy(section, column, index, offset) {
        const target = index + offset;
        if (target < 0 || target >= column.items.length) {
            return;
        }
        moveField(
            this.state.layout,
            { sectionId: section.id, columnId: column.id, index },
            { sectionId: section.id, columnId: column.id, index: offset > 0 ? target + 1 : target }
        );
    }

    onLayoutFieldDragStart(ev, section, column, index) {
        const item = column.items[index];
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData(
            "text/plain",
            JSON.stringify({
                kind: "field",
                name: item.name,
                from: { sectionId: section.id, columnId: column.id, index },
            })
        );
    }

    onDragOver(ev) {
        ev.preventDefault();
    }

    /** Drop on a column (index null) or before an item (index given). */
    onDropOnColumn(ev, section, column, index = null) {
        ev.preventDefault();
        ev.stopPropagation();
        const payload = readPayload(ev);
        if (!payload || payload.kind !== "field") {
            return;
        }
        const layout = this.state.layout;
        if (payload.from) {
            moveField(layout, payload.from, {
                sectionId: section.id,
                columnId: column.id,
                index,
            });
        } else {
            addField(layout, section.id, column.id, payload.name, index);
        }
        this.state.activeSectionId = section.id;
    }

    async onDropOnHeader(ev) {
        ev.preventDefault();
        const payload = readPayload(ev);
        if (!payload || payload.kind !== "button") {
            return;
        }
        const button = this.state.buttons.find((candidate) => candidate.id === payload.id);
        if (button) {
            await this.addButtonFromPalette(button);
        }
    }

    removeHeaderButton(index) {
        removeHeaderButton(this.state.layout, index);
    }

    // --- Saving -----------------------------------------------------------

    get canSave() {
        return this.isDirty() && !this.state.saving;
    }

    /**
     * Saves the layout as the arch of the form, replacing its root. The studio view
     * is created first if the form has none, then its arch is written verbatim.
     */
    async save() {
        if (!this.canSave) {
            return;
        }
        this.state.saving = true;
        try {
            await rpc("/web_studio/edit_page_layout", {
                view_id: this.state.viewId,
                arch: replaceRootArch(serializeFormLayout(this.state.layout), this.state.layout.rootTag),
                context: { studio: true },
            });
            await this.load();
            this.notification.add(_t("Page layout saved."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message?.message || _t("The page layout could not be saved."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    async discard() {
        await this.load();
    }
}

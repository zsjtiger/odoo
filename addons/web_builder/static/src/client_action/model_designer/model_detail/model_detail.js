import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    defaultActionForModel,
    useStudioServiceAsReactive,
    viewTypeToString,
} from "@web_builder/studio_service";
import { designerState } from "../designer_state";
import { FieldDetailPage } from "./field_detail_page";
import { getFieldTypeLabels } from "./field_types";
import { PageLayoutEditor } from "../page_layout/page_layout_editor";
import { ModelButtons } from "./model_buttons";
import { RecordTypeSection } from "../record_types/record_type_section";
import { NewFormViewDialog } from "./new_form_view_dialog";
import { NewListViewDialog } from "./new_list_view_dialog";
import { MobileSection } from "../mobile/mobile_section";
import { NewFieldDialog } from "./new_field_dialog";

const PAGE_SIZE = 100;
/** The form and list layouts come first, the others follow in their original order. */
const LAYOUT_PRIORITY = ["form", "list"];

export class ModelDetail extends Component {
    static template = "web_builder.ModelDetail";
    static components = { FieldDetailPage, ModelButtons, PageLayoutEditor, RecordTypeSection, MobileSection };

    props = useProps({
        model: t.object(),
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.studio = useStudioServiceAsReactive();
        this.designerState = designerState;
        this.fieldTypeLabels = getFieldTypeLabels();

        this.state = proxy({
            loading: true,
            fields: [],
            search: "",
            typeFilter: "all",
            limit: PAGE_SIZE,
        });

        this.filteredFields = computed(() => {
            const search = this.state.search.trim().toLowerCase();
            return this.state.fields.filter((field) => {
                if (this.state.typeFilter === "custom" && !field.isCustom) {
                    return false;
                }
                if (this.state.typeFilter === "standard" && field.isCustom) {
                    return false;
                }
                if (!search) {
                    return true;
                }
                return (
                    field.label.toLowerCase().includes(search) ||
                    field.name.toLowerCase().includes(search)
                );
            });
        });

        this.visibleFields = computed(() => this.filteredFields().slice(0, this.state.limit));

        this.state.mobile = null;
        this.state.forms = null;
        onWillStart(() => Promise.all([this.loadFields(this.props.model), this.loadMobile(this.props.model), this.loadForms(this.props.model)]));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.designerState.selectedFieldId = null;
                this.state.limit = PAGE_SIZE;
                this.state.loading = true;
                return Promise.all([this.loadFields(nextProps.model), this.loadMobile(nextProps.model), this.loadForms(nextProps.model)]);
            }
        });
    }

    /** Mobile action and form of the model (null when mobile_web is not installed). */
    async loadMobile(model) {
        const info = await this.orm.call("ir.model", "studio_mobile_infos", [model.model]);
        this.state.mobile = info.available ? info : null;
    }

    /** Form views of the model and where each one is used. */
    async loadForms(model) {
        this.state.forms = await this.orm.call("ir.model", "studio_form_views", [model.model]);
        this.state.lists = await this.orm.call("ir.model", "studio_list_views", [model.model]);
    }

    get listRows() {
        return (this.state.lists?.views || []).map((view) => ({
            ...view,
            kind: view.type === "kanban" ? "Kanban" : "List",
            devices: this.deviceIcons(view.used_by),
            usage: view.used_by.map((use) => this.usageLabel(use)).join(", ") || "Not used",
            editable: view.used_by.length > 0,
        }));
    }

    openNewList() {
        this.dialog.add(NewListViewDialog, {
            modelName: this.props.model.model,
            info: this.state.lists,
            onSaved: () => this.loadForms(this.props.model),
        });
    }

    /** Opens the list in Studio's view editor: on the PC action when it is used there, else on the mobile action. */
    async editList(view) {
        const usesPc = view.used_by.includes("pc");
        const actionId = usesPc ? this.state.lists.pc_action_id : this.state.lists.mobile_action_id;
        if (!actionId) {
            return;
        }
        const action = await this.action.loadAction(actionId);
        this.studio.setParams({ action, viewType: usesPc ? "list" : "kanban", mode: this.studio.MODES.EDITOR, editorTab: "views" });
    }

    get formRows() {
        return (this.state.forms?.views || []).map((view) => ({
            ...view,
            usage: view.used_by.map((use) => this.usageLabel(use)).join(", ") || "Not used",
            devices: this.deviceIcons(view.used_by),
            editable: view.used_by.length > 0,
        }));
    }

    /** Icons of the places a form is used in: PC, mobile (both icons when the form is used on both). */
    deviceIcons(usedBy) {
        const icons = [];
        if (usedBy.includes("pc")) {
            icons.push({ key: "pc", icon: "desktop_windows", title: "PC" });
        }
        if (usedBy.includes("mobile")) {
            icons.push({ key: "mobile", icon: "smartphone", title: "Mobile" });
        }
        for (const use of usedBy.filter((u) => u.startsWith("record_type:"))) {
            icons.push({ key: use, icon: "label", title: this.usageLabel(use) });
        }
        return icons;
    }

    usageLabel(use) {
        if (use === "pc") {
            return "PC";
        }
        if (use === "mobile") {
            return "Mobile";
        }
        const recordType = this.state.forms.record_types.find((rt) => `record_type:${rt.id}` === use);
        return recordType ? recordType.name : use;
    }

    openNewForm() {
        this.dialog.add(NewFormViewDialog, {
            modelName: this.props.model.model,
            info: this.state.forms,
            onSaved: () => this.loadForms(this.props.model),
        });
    }

    /** Opens the first place that uses the form in Studio's view editor. */
    async editForm(view) {
        const use = view.used_by[0];
        let actionId = false;
        if (use === "pc") {
            actionId = this.state.forms.pc_action_id;
        } else if (use === "mobile") {
            actionId = this.state.forms.mobile_action_id;
        } else if (use) {
            actionId = this.state.forms.record_types.find((rt) => `record_type:${rt.id}` === use)?.action_id;
        }
        if (!actionId) {
            return;
        }
        const action = await this.action.loadAction(actionId);
        this.studio.setParams({ action, viewType: "form", mode: this.studio.MODES.EDITOR, editorTab: "views" });
    }

    get mobileFormInfo() {
        return this.state.mobile;
    }

    /** Opens the mobile form (the form of the mobile kanban action) in Studio's view editor. */
    async openMobileForm() {
        const actionId = this.state.mobile?.mobile_action_id;
        if (!actionId) {
            return;
        }
        const action = await this.action.loadAction(actionId);
        this.studio.setParams({ action, viewType: "form", mode: this.studio.MODES.EDITOR, editorTab: "views" });
    }

    /** Opens the mobile list (the kanban of the mobile action) in Studio's view editor. */
    async openMobileList() {
        const actionId = this.state.mobile?.mobile_action_id;
        if (!actionId) {
            return;
        }
        const action = await this.action.loadAction(actionId);
        this.studio.setParams({ action, viewType: "kanban", mode: this.studio.MODES.EDITOR, editorTab: "views" });
    }

    async loadFields(model) {
        const fields = await this.orm.searchRead(
            "ir.model.fields",
            [["model", "=", model.model]],
            ["name", "field_description", "help", "ttype", "required", "relation", "state"],
            { order: "name ASC" }
        );
        this.state.fields = fields.map((field) => ({
            id: field.id,
            name: field.name,
            label: field.field_description,
            help: field.help || "",
            type: field.ttype,
            typeLabel: this.fieldTypeLabels[field.ttype] || field.ttype,
            required: field.required,
            relation: field.relation,
            isCustom: field.state === "manual",
        }));
        this.state.loading = false;
    }

    get hasMoreFields() {
        return this.filteredFields().length > this.state.limit;
    }

    showMoreFields() {
        this.state.limit += PAGE_SIZE;
    }

    setTypeFilter(filter) {
        this.state.typeFilter = filter;
        this.state.limit = PAGE_SIZE;
    }

    selectField(field) {
        this.designerState.selectedFieldId = field.id;
        this.designerState.section = "field";
    }

    /** Called by the field panel after a save or a delete. */
    async onFieldsChanged() {
        await this.loadFields(this.props.model);
    }

    /** The layouts of the model: form and list first, then the other views of its action. */
    get layoutTypes() {
        // The activity view is not designed here for now
        const viewTypes = (this.props.model.viewTypes.length
            ? [...this.props.model.viewTypes]
            : ["form", "list"]
        ).filter((viewType) => viewType !== "activity");
        // Every model has a search view, which is laid out like the others
        if (!viewTypes.includes("search")) {
            viewTypes.push("search");
        }
        const priority = (viewType) => {
            const index = LAYOUT_PRIORITY.indexOf(viewType);
            return index === -1 ? LAYOUT_PRIORITY.length : index;
        };
        return viewTypes.sort((a, b) => priority(a) - priority(b));
    }

    viewLabel(viewType) {
        return viewTypeToString(viewType);
    }

    get isFieldsSection() {
        return this.designerState.section === "fields" || this.designerState.section === "field";
    }

    get section() {
        return this.designerState.section;
    }

    showSection(section) {
        this.designerState.section = section;
        this.designerState.selectedFieldId = null;
    }

    get selectedFieldId() {
        return this.designerState.selectedFieldId;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.limit = PAGE_SIZE;
    }

    back() {
        this.designerState.selectedModelId = null;
        this.designerState.selectedModel = null;
        this.designerState.section = "fields";
        this.designerState.selectedFieldId = null;
    }

    /**
     * Opens the layout of the model for the given view type in the view editor.
     * @param {string} viewType
     */
    async openLayout(viewType) {
        const model = this.props.model;
        const action = model.actionId
            ? await this.action.loadAction(model.actionId)
            : defaultActionForModel({ model: model.model, view_type: viewType });
        this.studio.setParams({ action, viewType, mode: this.studio.MODES.EDITOR, editorTab: "views" });
    }

    /** Opens the form layout in Studio's own view editor, for the advanced changes. */
    openAdvancedEditor() {
        return this.openLayout("form");
    }

    /** Opens the page layout editor of a form or a list. */
    editPageLayout(viewType) {
        this.designerState.layoutViewType = viewType;
        this.showSection("page_layout");
    }

    backToLayouts() {
        this.showSection("layouts");
    }

    openNewField() {
        this.dialog.add(NewFieldDialog, {
            model: this.props.model,
            onCreated: () => this.loadFields(this.props.model),
        });
    }
}

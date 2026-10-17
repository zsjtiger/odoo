import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    defaultActionForModel,
    useStudioServiceAsReactive,
    viewTypeToString,
} from "@web_studio/studio_service";
import { designerState } from "../designer_state";
import { FieldDetailPanel } from "./field_detail_panel";
import { getFieldTypeLabels } from "./field_types";
import { NewFieldDialog } from "./new_field_dialog";

const PAGE_SIZE = 100;
/** The form and list layouts come first, the others follow in their original order. */
const LAYOUT_PRIORITY = ["form", "list"];

export class ModelDetail extends Component {
    static template = "web_studio.ModelDetail";
    static components = { FieldDetailPanel };

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
            selectedFieldId: null,
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

        this.selectedField = computed(() =>
            this.state.fields.find((field) => field.id === this.state.selectedFieldId)
        );

        onWillStart(() => this.loadFields(this.props.model));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.state.selectedFieldId = null;
                this.state.limit = PAGE_SIZE;
                this.state.loading = true;
                return this.loadFields(nextProps.model);
            }
        });
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
        this.state.selectedFieldId = field.id;
    }

    closeFieldPanel() {
        this.state.selectedFieldId = null;
    }

    /** Called by the field panel after a save or a delete. */
    async onFieldsChanged() {
        await this.loadFields(this.props.model);
    }

    /** The layouts of the model: form and list first, then the other views of its action. */
    get layoutTypes() {
        const viewTypes = this.props.model.viewTypes.length
            ? this.props.model.viewTypes
            : ["form", "list"];
        const priority = (viewType) => {
            const index = LAYOUT_PRIORITY.indexOf(viewType);
            return index === -1 ? LAYOUT_PRIORITY.length : index;
        };
        return [...viewTypes].sort((a, b) => priority(a) - priority(b));
    }

    viewLabel(viewType) {
        return viewTypeToString(viewType);
    }

    get isFieldsSection() {
        return this.designerState.section === "fields";
    }

    showSection(section) {
        this.designerState.section = section;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.limit = PAGE_SIZE;
    }

    back() {
        this.designerState.selectedModelId = null;
        this.designerState.selectedModel = null;
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
        this.studio.setParams({ action, viewType, editorTab: "views" });
    }

    openNewField() {
        this.dialog.add(NewFieldDialog, {
            model: this.props.model,
            onCreated: () => this.loadFields(this.props.model),
        });
    }
}

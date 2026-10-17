import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { defaultActionForModel, useStudioServiceAsReactive, viewTypeToString } from "@web_studio/studio_service";
import { designerState } from "../designer_state";
import { getFieldTypeLabels } from "./field_types";
import { NewFieldDialog } from "./new_field_dialog";

const LAYOUT_PRIORITY = ["form", "list"];

export class ModelDetail extends Component {
    static template = "web_studio.ModelDetail";

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

        this.state = proxy({ loading: true, fields: [], search: "" });

        this.filteredFields = computed(() => {
            const search = this.state.search.trim().toLowerCase();
            if (!search) {
                return this.state.fields;
            }
            return this.state.fields.filter(
                (field) =>
                    field.label.toLowerCase().includes(search) ||
                    field.name.toLowerCase().includes(search)
            );
        });

        onWillStart(() => this.loadFields(this.props.model));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.state.loading = true;
                return this.loadFields(nextProps.model);
            }
        });
    }

    async loadFields(model) {
        const fields = await this.orm.searchRead(
            "ir.model.fields",
            [["model", "=", model.model]],
            ["name", "field_description", "ttype", "required", "state"],
            { order: "name ASC" }
        );
        this.state.fields = fields.map((field) => ({
            id: field.id,
            name: field.name,
            label: field.field_description,
            type: field.ttype,
            typeLabel: this.fieldTypeLabels[field.ttype] || field.ttype,
            required: field.required,
            isCustom: field.state === "manual",
        }));
        this.state.loading = false;
    }

    /** The form and list layouts come first, the others follow in their original order. */
    get layoutTypes() {
        const viewTypes = this.props.model.viewTypes.length
            ? this.props.model.viewTypes
            : ["form", "list"];
        const priority = (viewType) => LAYOUT_PRIORITY.indexOf(viewType);
        return [...viewTypes].sort((a, b) => {
            const pa = priority(a) === -1 ? LAYOUT_PRIORITY.length : priority(a);
            const pb = priority(b) === -1 ? LAYOUT_PRIORITY.length : priority(b);
            return pa - pb;
        });
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
    }

    back() {
        this.designerState.selectedModelId = null;
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

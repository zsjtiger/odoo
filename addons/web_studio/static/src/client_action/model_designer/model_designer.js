import { Component, computed, onWillStart, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { viewTypeToString } from "@web_studio/studio_service";
import { designerState } from "./designer_state";
import { ModelDetail } from "./model_detail/model_detail";

/**
 * Object-manager style entry point of Studio: a list of the models, and for
 * the selected one its fields and page layouts.
 */
export class ModelDesigner extends Component {
    static template = "web_studio.ModelDesigner";
    static components = { ModelDetail };

    setup() {
        this.orm = useService("orm");

        this.state = proxy({
            loading: true,
            models: [],
            search: "",
            filter: "all",
        });

        this.filteredModels = computed(() => {
            const search = this.state.search.trim().toLowerCase();
            return this.state.models.filter((model) => {
                if (this.state.filter === "custom" && !model.isCustom) {
                    return false;
                }
                if (this.state.filter === "standard" && model.isCustom) {
                    return false;
                }
                if (!search) {
                    return true;
                }
                return (
                    model.name.toLowerCase().includes(search) ||
                    model.model.toLowerCase().includes(search)
                );
            });
        });

        this.selectedModel = computed(() =>
            this.state.models.find((model) => model.id === designerState.selectedModelId)
        );

        onWillStart(() => this.loadModels());
    }

    async loadModels() {
        const models = await this.orm.searchRead(
            "ir.model",
            [["transient", "=", false]],
            ["name", "model", "state"],
            { order: "name ASC" }
        );
        const modelNames = models.map((model) => model.model);
        const actions = await this.orm.searchRead(
            "ir.actions.act_window",
            [["res_model", "in", modelNames]],
            ["res_model", "view_mode"],
            { order: "id ASC" }
        );
        const actionByModel = {};
        for (const action of actions) {
            // Keep the first action of each model, it's the one Studio edits by default
            actionByModel[action.res_model] ??= action;
        }

        this.state.models = models.map((model) => {
            const action = actionByModel[model.model];
            return {
                id: model.id,
                name: model.name,
                model: model.model,
                isCustom: model.state === "manual",
                actionId: action?.id,
                viewTypes: action ? action.view_mode.split(",") : [],
            };
        });
        this.state.loading = false;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    viewLabel(viewType) {
        return viewTypeToString(viewType);
    }

    selectModel(model) {
        designerState.selectedModelId = model.id;
        designerState.selectedModel = { id: model.id, name: model.name, model: model.model };
        designerState.section = "fields";
    }
}

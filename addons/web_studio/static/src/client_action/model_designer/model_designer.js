import { Component, computed, onWillStart, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { defaultActionForModel, useStudioServiceAsReactive, viewTypeToString } from "@web_studio/studio_service";

/**
 * Model-centric entry point of Studio: lists the models and opens the layout
 * (form, list, ...) of the chosen model in the view editor.
 */
export class ModelDesigner extends Component {
    static template = "web_studio.ModelDesigner";

    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.studio = useStudioServiceAsReactive();

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

    viewLabel(viewType) {
        return viewTypeToString(viewType);
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    /**
     * Opens the given layout of a model in the view editor.
     * Models without any action get a default action, as the router does for models.
     * @param {Object} model
     * @param {string} viewType
     */
    async openLayout(model, viewType) {
        const action = model.actionId
            ? await this.action.loadAction(model.actionId)
            : defaultActionForModel({ model: model.model, view_type: viewType });
        this.studio.setParams({ action, viewType, editorTab: "views" });
    }

    /**
     * Opens the model with its first available layout (the default view of its action).
     * @param {Object} model
     */
    openModel(model) {
        const viewType = model.viewTypes[0] || "list";
        return this.openLayout(model, viewType);
    }
}

registry
    .category("web_studio.editor_tabs")
    .add("models", { name: _t("Models"), action: "web_studio.model_designer" }, { sequence: 5 });
registry.category("actions").add("web_studio.model_designer", ModelDesigner);

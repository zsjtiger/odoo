import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { STUDIO_MODULE } from "../page_layout/page_layout_model";

/** Buttons every record has, as in Salesforce's standard buttons. */
export const STANDARD_BUTTONS = [
    { name: _t("Edit"), help: _t("Open the record in edit mode") },
    { name: _t("Delete"), help: _t("Delete the record") },
    { name: _t("Clone"), help: _t("Create a copy of the record") },
];

/**
 * Builds the Python code of a server action that opens a URL.
 * The {id} placeholder in the URL is replaced by the id of the record.
 * @param {string} url
 * @returns {string}
 */
export function urlButtonCode(url) {
    return [
        `url = ${JSON.stringify(url)}`,
        `action = {`,
        `    "type": "ir.actions.act_url",`,
        `    "url": url.replace("{id}", str(records[:1].id)),`,
        `    "target": "new",`,
        `}`,
    ].join("\n");
}

/** Where a button appears, as the binding view types of the server action. */
export const BUTTON_PLACES = {
    form: "form",
    list: "list",
};

export class ModelButtons extends Component {
    static template = "web_builder.ModelButtons";

    props = useProps({
        model: t.object(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.standardButtons = STANDARD_BUTTONS;

        this.state = proxy({ loading: true, buttons: [] });

        this.customButtons = computed(() => this.state.buttons.filter((button) => button.isCustom));
        this.moduleButtons = computed(() => this.state.buttons.filter((button) => !button.isCustom));

        onWillStart(() => this.load(this.props.model));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.state.loading = true;
                return this.load(nextProps.model);
            }
        });
    }

    async load(model) {
        const actions = await this.orm.searchRead(
            "ir.actions.server",
            [
                ["binding_model_id", "=", model.id],
                ["binding_type", "=", "action"],
            ],
            ["name", "state", "code", "binding_view_types"],
            { order: "name ASC" }
        );
        // Actions defined by a module are standard, the ones created in Studio are custom
        // The xml ids created by Studio (to place a button on a layout) don't count
        const moduleRecords = actions.length
            ? await this.orm.searchRead(
                  "ir.model.data",
                  [
                      ["model", "=", "ir.actions.server"],
                      ["res_id", "in", actions.map((action) => action.id)],
                      ["module", "!=", STUDIO_MODULE],
                  ],
                  ["res_id"]
              )
            : [];
        const standardIds = new Set(moduleRecords.map((record) => record.res_id));
        this.state.buttons = actions.map((action) => ({
            id: action.id,
            name: action.name,
            isCustom: !standardIds.has(action.id),
            isUrl: action.state === "code" && action.code.includes("ir.actions.act_url"),
            places: action.binding_view_types.split(",").filter(Boolean),
        }));
        this.state.loading = false;
    }

    placeLabel(places) {
        const labels = [];
        if (places.includes(BUTTON_PLACES.form)) {
            labels.push(_t("Detail page"));
        }
        if (places.includes(BUTTON_PLACES.list)) {
            labels.push(_t("List view"));
        }
        return labels.join(", ") || _t("Nowhere");
    }

    openNewButton() {
        this.dialog.add(NewButtonDialog, {
            model: this.props.model,
            onCreated: () => this.load(this.props.model),
        });
    }

    remove(button) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Button"),
            body: _t("Delete the button %s? This can't be undone.", button.name),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("ir.actions.server", [button.id], {
                    context: { studio: true },
                });
                await this.load(this.props.model);
            },
            cancel: () => {},
        });
    }
}

export class NewButtonDialog extends Component {
    static template = "web_builder.ModelButtons.NewButtonDialog";
    static components = { Dialog };

    props = useProps({
        model: t.object(),
        onCreated: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            label: "",
            behavior: "url",
            url: "",
            code: "",
            detail: true,
            list: true,
            saving: false,
        });
        this.canCreate = computed(() => {
            if (this.state.saving || !this.state.label.trim()) {
                return false;
            }
            if (!this.state.detail && !this.state.list) {
                return false;
            }
            return this.state.behavior === "url" ? this.state.url.trim() !== "" : this.state.code.trim() !== "";
        });
    }

    onLabelInput(ev) {
        this.state.label = ev.target.value;
    }

    onBehaviorChange(ev) {
        this.state.behavior = ev.target.value;
    }

    onUrlInput(ev) {
        this.state.url = ev.target.value;
    }

    onCodeInput(ev) {
        this.state.code = ev.target.value;
    }

    onDetailChange(ev) {
        this.state.detail = ev.target.checked;
    }

    onListChange(ev) {
        this.state.list = ev.target.checked;
    }

    buildValues() {
        const places = [];
        if (this.state.detail) {
            places.push(BUTTON_PLACES.form);
        }
        if (this.state.list) {
            places.push(BUTTON_PLACES.list);
        }
        return {
            name: this.state.label.trim(),
            model_id: this.props.model.id,
            binding_model_id: this.props.model.id,
            binding_type: "action",
            binding_view_types: places.join(","),
            state: "code",
            code:
                this.state.behavior === "url" ? urlButtonCode(this.state.url.trim()) : this.state.code,
        };
    }

    async onConfirm() {
        if (!this.canCreate()) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.create("ir.actions.server", [this.buildValues()], {
                context: { studio: true },
            });
            await this.props.onCreated();
            this.props.close();
        } catch (error) {
            this.notification.add(error.message?.message || _t("The button could not be created."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }
}

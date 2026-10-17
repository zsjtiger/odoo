import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { designerState } from "../designer_state";
import { getFieldTypeLabels } from "./field_types";

const SELECTION_FIELDS = ["value", "name", "sequence"];

/**
 * Turns a picklist label into a technical value, unique among the given values.
 * @param {string} name
 * @param {string[]} takenValues
 * @returns {string}
 */
export function labelToOptionValue(name, takenValues) {
    const base =
        name
            .trim()
            .toLowerCase()
            .normalize("NFD")
            .replace(/[̀-ͯ]/g, "")
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, "") || "value";
    let value = base;
    let suffix = 2;
    while (takenValues.includes(value)) {
        value = `${base}_${suffix++}`;
    }
    return value;
}

/**
 * Full page of a field, the way Salesforce's field detail page works:
 * field information, relationship and picklist values.
 * Standard fields can be relabelled and documented only; custom fields can be
 * fully edited and deleted.
 */
export class FieldDetailPage extends Component {
    static template = "web_studio.FieldDetailPage";

    props = useProps({
        model: t.object(),
        fieldId: t.number(),
        onChanged: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.labels = getFieldTypeLabels();
        this.designerState = designerState;

        this.state = proxy({
            loading: true,
            saving: false,
            field: null,
            label: "",
            help: "",
            required: false,
            options: [],
            removedOptionIds: [],
        });

        this.isDirty = computed(() => this.hasChanges());
        this.canSave = computed(
            () =>
                this.isDirty() &&
                !this.state.saving &&
                this.state.label.trim() !== "" &&
                this.state.options.every((option) => option.name.trim() !== "")
        );

        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.fieldId !== this.props.fieldId) {
                this.state.loading = true;
                return this.load(nextProps.fieldId);
            }
        });
    }

    async load(fieldId = this.props.fieldId) {
        const [record] = await this.orm.read(
            "ir.model.fields",
            [fieldId],
            ["name", "field_description", "help", "ttype", "required", "relation", "relation_table", "state", "selection_ids"]
        );
        const options = record.selection_ids.length
            ? await this.orm.read("ir.model.fields.selection", record.selection_ids, SELECTION_FIELDS)
            : [];
        const sorted = [...options].sort((a, b) => a.sequence - b.sequence);
        this.state.field = {
            id: record.id,
            name: record.name,
            label: record.field_description,
            help: record.help || "",
            type: record.ttype,
            typeLabel: this.labels[record.ttype] || record.ttype,
            required: record.required,
            relation: record.relation,
            relationTable: record.relation_table,
            isCustom: record.state === "manual",
        };
        this.state.label = record.field_description;
        this.state.help = record.help || "";
        this.state.required = record.required;
        this.state.options = sorted.map((option) => this.optionFromRecord(option));
        this.state.removedOptionIds = [];
        this.state.loading = false;
    }

    optionFromRecord(option) {
        return {
            id: option.id,
            value: option.value,
            name: option.name,
            originalName: option.name,
            originalSequence: option.sequence,
        };
    }

    get isSelection() {
        return this.state.field?.type === "selection";
    }

    get isRelation() {
        return ["many2one", "many2many", "one2many"].includes(this.state.field?.type);
    }

    get isCustom() {
        return this.state.field?.isCustom;
    }

    /** Commands to update the picklist values, empty when nothing changed. */
    optionCommands() {
        const commands = [];
        for (const id of this.state.removedOptionIds) {
            commands.push([2, id]);
        }
        const takenValues = this.state.options.filter((option) => option.value).map((option) => option.value);
        this.state.options.forEach((option, index) => {
            const sequence = index + 1;
            if (option.id) {
                if (option.name !== option.originalName || sequence !== option.originalSequence) {
                    commands.push([1, option.id, { name: option.name.trim(), sequence }]);
                }
            } else {
                const value = labelToOptionValue(option.name, takenValues);
                takenValues.push(value);
                commands.push([0, 0, { value, name: option.name.trim(), sequence }]);
            }
        });
        return commands;
    }

    hasChanges() {
        if (!this.state.field) {
            return false;
        }
        const field = this.state.field;
        return (
            this.state.label !== field.label ||
            this.state.help !== field.help ||
            (field.isCustom && this.state.required !== field.required) ||
            (this.isSelection && field.isCustom && this.optionCommands().length > 0)
        );
    }

    /** Only the values that changed, with the studio context. */
    buildValues() {
        const field = this.state.field;
        const values = {};
        if (this.state.label.trim() !== field.label) {
            values.field_description = this.state.label.trim();
        }
        if (this.state.help !== field.help) {
            values.help = this.state.help;
        }
        if (field.isCustom && this.state.required !== field.required) {
            values.required = this.state.required;
        }
        if (this.isSelection && field.isCustom) {
            const commands = this.optionCommands();
            if (commands.length) {
                values.selection_ids = commands;
            }
        }
        return values;
    }

    onLabelInput(ev) {
        this.state.label = ev.target.value;
    }

    onHelpInput(ev) {
        this.state.help = ev.target.value;
    }

    onRequiredChange(ev) {
        this.state.required = ev.target.checked;
    }

    onOptionNameInput(option, ev) {
        option.name = ev.target.value;
    }

    moveOption(index, offset) {
        const target = index + offset;
        const options = this.state.options;
        if (target < 0 || target >= options.length) {
            return;
        }
        [options[index], options[target]] = [options[target], options[index]];
    }

    removeOption(index) {
        const [option] = this.state.options.splice(index, 1);
        if (option.id) {
            this.state.removedOptionIds.push(option.id);
        }
    }

    addOption() {
        this.state.options.push({ id: null, value: "", name: "", originalName: "", originalSequence: 0 });
    }

    backToFields() {
        this.designerState.section = "fields";
        this.designerState.selectedFieldId = null;
    }

    backToModel() {
        this.backToFields();
    }

    backToModels() {
        this.designerState.selectedModelId = null;
        this.designerState.selectedModel = null;
        this.designerState.section = "fields";
        this.designerState.selectedFieldId = null;
    }

    async save() {
        if (!this.canSave()) {
            return;
        }
        const values = this.buildValues();
        if (!Object.keys(values).length) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.write("ir.model.fields", [this.state.field.id], values, {
                context: { studio: true },
            });
            await this.load();
            await this.props.onChanged();
            this.notification.add(_t("Field saved."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message?.message || _t("The field could not be saved."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    remove() {
        const field = this.state.field;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Field"),
            body: _t("Delete the field %s? Its data will be lost and this can't be undone.", field.label),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("ir.model.fields", [field.id], {
                    context: { studio: true },
                });
                await this.props.onChanged();
                this.backToFields();
            },
            cancel: () => {},
        });
    }
}

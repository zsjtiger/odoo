import { Component, computed, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { designerState } from "../designer_state";
import { getFieldTypeLabels } from "./field_types";
import { relationTableName } from "./new_field_dialog";

/** Domain generated from a dependency: [(target, '=', dependency)] if dependency else [] */
const DEPENDENCY_DOMAIN_REGEX = /^\[\('(\w+)', '(?:=|in)', (\w+)\)\] if \2 else \[\]$/;

/**
 * @param {string|false} domain
 * @returns {{ targetField: string, dependsOn: string } | null} the parts of a generated domain
 */
function parseDependencyDomain(domain) {
    const match = domain && domain.match(DEPENDENCY_DOMAIN_REGEX);
    return match ? { targetField: match[1], dependsOn: match[2] } : null;
}

/** The field type of the candidates matching a dependency of the given type. */
function targetTypeOf(dependsType) {
    return ["many2many", "one2many"].includes(dependsType) ? "many2one" : dependsType;
}

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
    static template = "web_builder.FieldDetailPage";

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
            relation: "",
            dependsOn: "",
            targetField: "",
            dependsFields: [],
            targetFields: [],
            models: [],
            takenTables: [],
        });

        this.isDirty = computed(() => this.hasChanges());
        this.canSave = computed(
            () =>
                this.isDirty() &&
                !this.state.saving &&
                this.state.label.trim() !== "" &&
                this.state.options.every((option) => option.name.trim() !== "")
        );

        onWillStart(async () => {
            const [models, manyFields] = await Promise.all([
                this.orm.searchRead("ir.model", [["transient", "=", false]], ["name", "model"], {
                    order: "name ASC",
                }),
                this.orm.searchRead("ir.model.fields", [["ttype", "=", "many2many"]], ["relation_table"]),
            ]);
            this.state.models = models;
            this.state.takenTables = manyFields.map((field) => field.relation_table);
            await this.load();
        });
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
            ["name", "field_description", "help", "ttype", "required", "relation", "relation_table", "state", "selection_ids", "depends_on", "domain"]
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
            dependsOn: record.depends_on || "",
            targetField: parseDependencyDomain(record.domain)?.targetField || "",
            isGeneratedDomain: Boolean(parseDependencyDomain(record.domain)),
        };
        this.state.label = record.field_description;
        this.state.help = record.help || "";
        this.state.required = record.required;
        this.state.relation = record.relation || "";
        this.state.dependsOn = record.depends_on || "";
        this.state.targetField = this.state.field.targetField;
        this.state.options = sorted.map((option) => this.optionFromRecord(option));
        this.state.removedOptionIds = [];
        this.state.loading = false;
        await this.loadDependsOnOptions();
        await this.loadTargetOptions();
    }

    /** Fields of the model that the field may depend on, any type but itself. */
    async loadDependsOnOptions() {
        this.state.dependsFields = await this.orm.searchRead(
            "ir.model.fields",
            [["model", "=", this.props.model.model], ["name", "!=", this.state.field.name]],
            ["name", "field_description", "ttype"],
            { order: "field_description ASC" }
        );
    }

    /** Stored fields of the related model that the dependency value is compared with. */
    async loadTargetOptions() {
        this.state.targetFields = [];
        const dependsField = this.state.dependsFields.find((field) => field.name === this.state.dependsOn);
        if (!dependsField || !this.state.field.relation) {
            return;
        }
        this.state.targetFields = await this.orm.searchRead(
            "ir.model.fields",
            [
                ["model", "=", this.state.field.relation],
                ["ttype", "=", targetTypeOf(dependsField.ttype)],
                ["store", "=", true],
            ],
            ["name", "field_description"],
            { order: "field_description ASC" }
        );
    }

    async onDependsOnChange(ev) {
        this.state.dependsOn = ev.target.value;
        this.state.targetField = "";
        await this.loadTargetOptions();
    }

    onTargetFieldChange(ev) {
        this.state.targetField = ev.target.value;
    }

    /** Only a custom many2one can depend on another field: its candidates are filtered. */
    get canDependOn() {
        return this.isCustom && this.state.field?.type === "many2one";
    }

    /**
     * Domain filtering the candidates by the value of the dependency, empty when the
     * dependency is not fully configured.
     * @returns {string|false}
     */
    dependencyDomain() {
        const { dependsOn, targetField } = this.state;
        const dependsField = this.state.dependsFields.find((field) => field.name === dependsOn);
        if (!dependsField || !targetField) {
            return false;
        }
        const operator = ["many2many", "one2many"].includes(dependsField.ttype) ? "in" : "=";
        return `[('${targetField}', '${operator}', ${dependsOn})] if ${dependsOn} else []`;
    }

    hasDependencyChanges() {
        const field = this.state.field;
        return (
            this.state.dependsOn !== field.dependsOn || this.state.targetField !== field.targetField
        );
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

    /** A custom lookup or multi-select lookup can point to another model. */
    get canChangeRelation() {
        return this.isCustom && ["many2one", "many2many"].includes(this.state.field?.type);
    }

    /** Changing the related model of a many2many moves its links to a new junction table. */
    get relationChangeLosesLinks() {
        return this.canChangeRelation && this.state.field.type === "many2many" && this.state.relation !== this.state.field.relation;
    }

    onRelationChange(ev) {
        this.state.relation = ev.target.value;
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
            (this.canChangeRelation && this.state.relation !== field.relation) ||
            (this.canDependOn && this.hasDependencyChanges()) ||
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
        if (this.canChangeRelation && this.state.relation !== field.relation) {
            values.relation = this.state.relation;
            if (field.type === "many2many") {
                values.relation_table = relationTableName(
                    this.props.model.model,
                    this.state.relation,
                    this.state.takenTables
                );
            }
        }
        if (this.canDependOn && this.hasDependencyChanges()) {
            const domain = this.dependencyDomain();
            values.depends_on = domain ? this.state.dependsOn : false;
            // the generated domain replaces the previous one only if it was generated too
            if (domain) {
                values.domain = domain;
            } else if (field.isGeneratedDomain) {
                values.domain = "[]";
            }
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
        if (this.relationChangeLosesLinks) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Change Related Model"),
                body: _t(
                    "The existing links of %s are not kept: the field will use a new junction table, empty. Continue?",
                    this.state.field.label
                ),
                confirmLabel: _t("Change"),
                confirmClass: "btn-danger",
                confirm: () => this.doSave(),
                cancel: () => {},
            });
            return;
        }
        await this.doSave();
    }

    async doSave() {
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

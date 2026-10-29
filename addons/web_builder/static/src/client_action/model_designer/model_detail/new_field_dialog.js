import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { getFieldTypeLabels } from "./field_types";

/** Field types that only need a label: relations and picklists are handled below. */
const SIMPLE_TYPES = [
    "char",
    "text",
    "html",
    "integer",
    "float",
    "monetary",
    "boolean",
    "date",
    "datetime",
];
const RELATION_TYPES = ["many2one", "many2many", "selection"];

/**
 * Turns a label into a technical name, the way Studio names custom fields.
 * @param {string} label
 * @returns {string}
 */
export function labelToFieldName(label) {
    const slug = slugify(label);
    return slug ? `x_${slug}` : "";
}

/**
 * @param {string} text
 * @returns {string} lowercase ascii, words separated by underscores
 */
function slugify(text) {
    return text
        .trim()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
}

/**
 * Name of the junction table of a many2many field, unique among the given tables.
 * @param {string} model technical name of the model that owns the field
 * @param {string} relation technical name of the related model
 * @param {string[]} takenTables
 * @returns {string}
 */
export function relationTableName(model, relation, takenTables) {
    const base = `x_${model.replace(/\./g, "_")}_${relation.replace(/\./g, "_")}_rel`.slice(0, 55);
    let name = base;
    let suffix = 2;
    while (takenTables.includes(name)) {
        name = `${base}_${suffix++}`;
    }
    return name;
}

/**
 * Parses the picklist values typed one per line.
 * @param {string} text
 * @returns {Array<{value: string, name: string}>}
 */
export function parsePicklistValues(text) {
    const values = [];
    const seen = new Set();
    for (const line of text.split("\n")) {
        const name = line.trim();
        const value = slugify(name);
        if (!name || !value || seen.has(value)) {
            continue;
        }
        seen.add(value);
        values.push({ value, name });
    }
    return values;
}

export class NewFieldDialog extends Component {
    static template = "web_builder.ModelDetail.NewFieldDialog";
    static components = { Dialog };

    props = useProps({
        model: t.object(),
        onCreated: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const labels = getFieldTypeLabels();
        this.typeOptions = [...SIMPLE_TYPES, ...RELATION_TYPES].map((value) => ({
            value,
            label: labels[value],
        }));
        this.state = proxy({
            label: "",
            name: "",
            nameEdited: false,
            type: "char",
            relation: "",
            picklist: "",
            models: [],
            saving: false,
        });

        this.takenTables = [];
        onWillStart(async () => {
            [this.state.models, this.takenTables] = await Promise.all([
                this.orm.searchRead("ir.model", [["transient", "=", false]], ["name", "model"], {
                    order: "name ASC",
                }),
                this.orm.searchRead("ir.model.fields", [["ttype", "=", "many2many"]], ["relation_table"]),
            ]).then(([models, fields]) => [models, fields.map((field) => field.relation_table)]);
        });
    }

    get isLookup() {
        return this.state.type === "many2one" || this.state.type === "many2many";
    }

    get isPicklist() {
        return this.state.type === "selection";
    }

    onLabelInput(ev) {
        this.state.label = ev.target.value;
        if (!this.state.nameEdited) {
            this.state.name = labelToFieldName(this.state.label);
        }
    }

    onNameInput(ev) {
        this.state.name = ev.target.value;
        this.state.nameEdited = true;
    }

    onTypeChange(ev) {
        this.state.type = ev.target.value;
    }

    onRelationChange(ev) {
        this.state.relation = ev.target.value;
    }

    onPicklistInput(ev) {
        this.state.picklist = ev.target.value;
    }

    get canCreate() {
        if (this.state.saving || !this.state.label.trim() || !this.state.name) {
            return false;
        }
        if (this.isLookup) {
            return Boolean(this.state.relation);
        }
        if (this.isPicklist) {
            return parsePicklistValues(this.state.picklist).length > 0;
        }
        return true;
    }

    buildValues() {
        const values = {
            model_id: this.props.model.id,
            name: this.state.name,
            field_description: this.state.label.trim(),
            ttype: this.state.type,
        };
        if (this.isLookup) {
            values.relation = this.state.relation;
        }
        if (this.state.type === "many2many") {
            values.relation_table = relationTableName(
                this.props.model.model,
                this.state.relation,
                this.takenTables
            );
        }
        if (this.isPicklist) {
            values.selection_ids = parsePicklistValues(this.state.picklist).map(
                (option, index) => [0, 0, { ...option, sequence: index + 1 }]
            );
        }
        return values;
    }

    async onConfirm() {
        if (!this.canCreate) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.create("ir.model.fields", [this.buildValues()], {
                context: { studio: true },
            });
            await this.props.onCreated();
            this.props.close();
        } catch (error) {
            this.notification.add(error.message?.message || _t("The field could not be created."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }
}

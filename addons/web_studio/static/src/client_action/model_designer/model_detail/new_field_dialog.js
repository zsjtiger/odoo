import { Component, proxy, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { getFieldTypeLabels } from "./field_types";

/** Field types that don't need extra configuration (relations, picklists...). */
const SIMPLE_TYPES = ["char", "text", "html", "integer", "float", "monetary", "boolean", "date", "datetime"];

/**
 * Turns a label into a technical name, the way Studio names custom fields.
 * @param {string} label
 * @returns {string}
 */
export function labelToFieldName(label) {
    const slug = label
        .trim()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    return slug ? `x_${slug}` : "";
}

export class NewFieldDialog extends Component {
    static template = "web_studio.ModelDetail.NewFieldDialog";
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
        this.typeOptions = SIMPLE_TYPES.map((value) => ({ value, label: labels[value] }));
        this.state = proxy({
            label: "",
            name: "",
            nameEdited: false,
            type: "char",
            saving: false,
        });
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

    get canCreate() {
        return !this.state.saving && this.state.label.trim() && this.state.name;
    }

    async onConfirm() {
        if (!this.canCreate) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.create(
                "ir.model.fields",
                [
                    {
                        model_id: this.props.model.id,
                        name: this.state.name,
                        field_description: this.state.label.trim(),
                        ttype: this.state.type,
                    },
                ],
                { context: { studio: true } }
            );
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

import { Component, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Side panel showing the properties of a field of the model.
 * Standard fields only accept a new label and help text, custom fields
 * can also be made required or deleted.
 */
export class FieldDetailPanel extends Component {
    static template = "web_studio.FieldDetailPanel";

    props = useProps({
        field: t.object(),
        onChanged: t.function(),
        onClose: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = proxy({ label: "", help: "", required: false, saving: false });
        this.resetFromField(this.props.field);

        onWillUpdateProps((nextProps) => {
            if (nextProps.field.id !== this.props.field.id) {
                this.resetFromField(nextProps.field);
            }
        });
    }

    resetFromField(field) {
        this.state.label = field.label;
        this.state.help = field.help;
        this.state.required = field.required;
    }

    get isDirty() {
        const field = this.props.field;
        return (
            this.state.label !== field.label ||
            this.state.help !== field.help ||
            (field.isCustom && this.state.required !== field.required)
        );
    }

    get canSave() {
        return this.isDirty && !this.state.saving && this.state.label.trim() !== "";
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

    async save() {
        const field = this.props.field;
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
        if (!Object.keys(values).length) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.write("ir.model.fields", [field.id], values, {
                context: { studio: true },
            });
            await this.props.onChanged();
        } catch (error) {
            this.notification.add(error.message?.message || _t("The field could not be saved."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    remove() {
        const field = this.props.field;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Field"),
            body: _t(
                "Delete the field %s? Its data will be lost and this can't be undone.",
                field.label
            ),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("ir.model.fields", [field.id], {
                    context: { studio: true },
                });
                await this.props.onChanged();
                this.props.onClose();
            },
            cancel: () => {},
        });
    }
}

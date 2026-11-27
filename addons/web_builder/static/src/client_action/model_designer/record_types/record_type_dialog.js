import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

/** Create or edit a record type of the model. */
export class RecordTypeDialog extends Component {
    static template = "web_builder.RecordTypeDialog";
    static components = { Dialog };

    props = useProps({
        info: t.object(),
        type: t.object().optional(),
        onSaved: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const type = this.props.type;
        this.state = proxy({
            name: type?.name || "",
            code: type?.code || "",
            sequence: type?.sequence ?? 10,
            active: type ? type.active : true,
            allowImport: type ? type.allow_import : true,
            saving: false,
        });
    }

    get title() {
        return this.props.type ? "Edit Record Type" : "New Record Type";
    }

    get canSave() {
        return Boolean(this.state.name.trim() && this.state.code.trim()) && !this.state.saving;
    }

    async save() {
        this.state.saving = true;
        const values = {
            name: this.state.name.trim(),
            code: this.state.code.trim(),
            sequence: Number(this.state.sequence) || 0,
            active: this.state.active,
        };
        if (this.props.info.has_allow_import) {
            values.allow_import = this.state.allowImport;
        }
        try {
            if (this.props.type) {
                await this.orm.write("ir.record.type", [this.props.type.id], values);
            } else {
                await this.orm.create("ir.record.type", [{ ...values, model_id: this.props.info.model_id }]);
            }
            this.props.onSaved();
            this.props.close();
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || "Error", {
                type: "danger",
                sticky: true,
            });
        } finally {
            this.state.saving = false;
        }
    }
}

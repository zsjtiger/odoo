import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

/** Adds a field of a related record (a dotted many2one path) to the mobile list. */
export class MobileFieldDialog extends Component {
    static template = "web_builder.MobileFieldDialog";
    static components = { Dialog };

    props = useProps({
        modelId: t.number(),
        onSaved: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({ name: "", path: "", listView: true, store: false, sequence: 10, saving: false });
    }

    get canSave() {
        return Boolean(this.state.name.trim() && this.state.path.trim()) && !this.state.saving;
    }

    async save() {
        this.state.saving = true;
        try {
            await this.orm.create("mobile.custom.field", [{
                name: this.state.name.trim(),
                path: this.state.path.trim(),
                model_id: this.props.modelId,
                list_view: this.state.listView,
                store: this.state.store,
                sequence: Number(this.state.sequence) || 10,
            }]);
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

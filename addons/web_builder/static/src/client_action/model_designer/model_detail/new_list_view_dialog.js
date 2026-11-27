import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

/** Adds a list of the model and puts it in a slot: the PC action, the mobile action, or both. */
export class NewListViewDialog extends Component {
    static template = "web_builder.NewListViewDialog";
    static components = { Dialog };

    props = useProps({
        modelName: t.string(),
        info: t.object(),
        onSaved: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            name: "",
            slot: this.props.info.pc_action_id ? "pc" : "mobile",
            saving: false,
        });
    }

    get slots() {
        const slots = [];
        if (this.props.info.pc_action_id) {
            slots.push({ key: "pc", label: "PC list" });
        }
        if (this.props.info.mobile_action_id) {
            slots.push({ key: "mobile", label: "Mobile list" });
        }
        if (this.props.info.pc_action_id && this.props.info.mobile_action_id) {
            slots.push({ key: "both", label: "PC and mobile" });
        }
        return slots;
    }

    get canSave() {
        return Boolean(this.state.name.trim()) && !this.state.saving;
    }

    async save() {
        this.state.saving = true;
        try {
            await this.orm.call("ir.model", "studio_create_list_view", [this.props.modelName], {
                name: this.state.name.trim(),
                slot: this.state.slot,
            });
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

import { Component, onWillStart, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * "PC / Mobile" switch of the view editor: editing the form of the PC action or of the
 * mobile action of the model. The mobile form is a separate form, see mobile_config_design.md.
 */
export class DeviceSwitch extends Component {
    static template = "web_builder.ViewEditor.DeviceSwitch";

    setup() {
        this.studio = useService("studio");
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ info: null });
        onWillStart(async () => {
            this.state.info = await this.orm.call("ir.model", "studio_mobile_infos", [
                this.studio.editedAction.res_model,
            ]);
        });
    }

    get available() {
        return Boolean(this.state.info?.available && this.state.info.mobile_action_id);
    }

    get current() {
        return this.studio.editedAction?.id === this.state.info?.mobile_action_id ? "mobile" : "pc";
    }

    async switchTo(device) {
        if (device === this.current) {
            return;
        }
        const actionId = device === "mobile" ? this.state.info.mobile_action_id : this.state.info.action_id;
        if (!actionId) {
            return;
        }
        const action = await this.action.loadAction(actionId);
        this.studio.setParams({ action, viewType: "form" });
    }
}

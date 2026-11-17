import { Component, xml, onWillDestroy } from "@odoo/owl";
import { render } from "@web/core/owl/utils";
import { MobileActionMenu } from "@mobile_web/actions/action_menu/action_menu";
import { envOf } from "@mobile_web/core/env";


export class MobileActionContainer extends Component {
    static components = { MobileActionMenu };
    static template = xml`
        <t t-name="mobile_web.MobileActionContainer">
            <div class="m_action_manager">
                <t t-if="this.info.Component" t-component="this.info.Component" className="'m_action'" t-props="this.info.componentProps" t-key="this.info.id"/>
            </div>

            <MobileActionMenu actions="this.info.currentActions"/>
        </t>
    `;

    setup() {
        this.info = {};
        this.onActionManagerUpdate = ({ detail: info }) => {
            this.info = info;
            render(this);
        };

        envOf(this).bus.addEventListener("ACTION_MANAGER:UPDATE", this.onActionManagerUpdate);
        onWillDestroy(() => {
            envOf(this).bus.removeEventListener("ACTION_MANAGER:UPDATE", this.onActionManagerUpdate);
        });
    }
}

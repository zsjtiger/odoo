import { Component, xml, onWillDestroy } from "@crossnow/owl";
import { MobileActionMenu } from './action_menu';


export class MobileActionContainer extends Component {
    static components = { MobileActionMenu };
    static props = {};
    static template = xml`
        <t t-name="mobile_web.MobileActionContainer">
            <div class="m_action_manager">
                <t t-if="info.Component" t-component="info.Component" className="'m_action'" t-props="info.componentProps" t-key="info.id"/>
            </div>

            <MobileActionMenu actions="info.currentActions"/>
        </t>
    `;

    setup() {
        this.info = {};
        this.onActionManagerUpdate = ({ detail: info }) => {
            this.info = info;
            this.render();
        };

        this.env.bus.addEventListener("ACTION_MANAGER:UPDATE", this.onActionManagerUpdate);
        onWillDestroy(() => {
            this.env.bus.removeEventListener("ACTION_MANAGER:UPDATE", this.onActionManagerUpdate);
        });
    }
}

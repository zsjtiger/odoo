import { Component, xml } from "@crossnow/owl";
import { useService } from "@web/core/utils/hooks";

import { SvgIcon } from "../../../common/components/svg_icon";


export class ActionMenuItem extends Component {
    static components = {
        SvgIcon
    };
    static props = {
        name: String,
        action_id: Number,
        icon_href: String
    }
    static template = xml`
        <t t-name="mobile_web.MobileActionMenu.Item">
            <div class="action_menu_item" t-att="{'data-action-id': props.action_id}" t-on-click="_onActionMenuItemClick">
                <SvgIcon iconHref="props.icon_href" className="'action_icon'"/>

                <div class="action_name">
                    <t t-esc="props.name"/>
                </div>
            </div>
        </t>
    `;

    setup() {
        this.mobileActionService = useService('mobileAction');
    }

    _onActionMenuItemClick(ev) {
        const actionId = ev.currentTarget.dataset.actionId;
        this.mobileActionService.doAction(actionId);
    }
}


export class MobileActionMenu extends Component {
    static components = { ActionMenuItem };
    static props = {
        actions: Array
    };
    static defaultProps = {
        actions: []
    }
    static template = xml`
        <t t-name="mobile_web.MobileActionMenu">
            <div class="m_action_menu">
                <t t-if="props.actions" t-foreach="props.actions" t-as="action" t-key="action.name">
                    <ActionMenuItem name="action.name" action_id="action.action_id" icon_href="action.svg_icon_href"/>
                </t>
            </div>
        </t>
    `;
}

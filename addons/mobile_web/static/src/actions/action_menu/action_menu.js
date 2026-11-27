import { Component, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

import { SvgIcon } from "@mobile_web/widgets/svg_icon/svg_icon";


export class ActionMenuItem extends Component {
    static components = {
        SvgIcon
    };
    props = useProps({
        name: t.string(),
        action_id: t.number(),
        icon_href: t.string(),
    });
    static template = xml`
        <t t-name="mobile_web.MobileActionMenu.Item">
            <div class="action_menu_item" t-att="{'data-action-id': this.props.action_id}" t-on-click="this._onActionMenuItemClick">
                <SvgIcon iconHref="this.props.icon_href" className="'action_icon'"/>

                <div class="action_name">
                    <t t-esc="this.props.name"/>
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
    props = useProps({
        actions: t.array().optional([]),
    });
    static template = xml`
        <t t-name="mobile_web.MobileActionMenu">
            <div class="m_action_menu">
                <t t-if="this.props.actions" t-foreach="this.props.actions" t-as="action" t-key="action.name">
                    <ActionMenuItem name="action.name" action_id="action.action_id" icon_href="action.svg_icon_href"/>
                </t>
            </div>
        </t>
    `;
}

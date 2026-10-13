import { Component, xml, onWillDestroy } from "@crossnow/owl";
import { useService } from "@web/core/utils/hooks";

import { SvgIcon } from '@mobile_web/common/components/svg_icon'


export class MobileNavBar extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileNavBar">
          <div class="m_navbar">
            <div></div>
            <div class="m_navbar_title">
                <t t-if="renderInfo.title" t-esc="renderInfo.title"/>
            </div>
            <div class="m_navbar_return_home" t-on-click="this.onReturnHomeClick">
                <SvgIcon iconHref="renderInfo.returnHomeIconRef" className="'return_home_icon'"/>
            </div>
          </div>
        </t>
    `;
    static props = {};
    static components = {SvgIcon};

    setup() {
        this.renderInfo = {
            'returnHomeIconRef': '#crossnow-icon-Home'
        };
        this.mobileActionService = useService("mobileAction");
        
        this.onTitleUpdate = ({detail: info}) => {
            this.renderInfo = Object.assign(this.renderInfo, info);
            this.render();
        };

        this.env.bus.addEventListener("NAVBAR_TITLE:UPDATE", this.onTitleUpdate);
        onWillDestroy(() => {
            this.env.bus.removeEventListener("NAVBAR_TITLE:UPDATE", this.onTitleUpdate);
        });
    }

    onReturnHomeClick(ev) {
        this.mobileActionService.doAction("home");
    }
}

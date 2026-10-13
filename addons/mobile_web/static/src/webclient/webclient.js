// owl
import { Component, xml, onMounted, useExternalListener, useState } from "@crossnow/owl";

// crossnow web core
import { localization } from "@web/core/l10n/localization";
import { useBus, useService } from "@web/core/utils/hooks";
import { routerBus } from "@web/core/browser/router";
import { router } from '@mobile_web/core/browser/router';

// webclient components
import { MobileActionContainer } from "./actions/components/action_container";
import { MobileNavBar } from "./navbar/navbar";


export class MobileWebClient extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileWebClient">
            <div class="m_webclient">
                <MobileNavBar/>
                <MobileActionContainer/>

                <!-- TODO: 错误处理目前只是在webclient展示一个div，后续可能需要封装为弹窗？ -->
                <t t-if="state.error">
                    <div t-esc="state.error" style="color: red;"/>
                </t>
            </div>
        </t>
    `;
    static props = {};
    static components = {
        MobileNavBar,
        MobileActionContainer,
    };

    setup() {
        this.state = useState({error: false});  // TODO: 错误处理目前只是在webclient展示一个div，后续可能需要封装为弹窗？
        this.mobileActionService = useService("mobileAction");
        this.localization = localization;

        // life cycle
        onMounted(() => {
            this.loadRouterState();
            this.env.bus.trigger("WEB_CLIENT_READY");
        });

        useBus(routerBus, "ROUTE_CHANGE", this.loadRouterState)
        useExternalListener(window, "click", this.onGlobalClick, { capture: true });
    };

    /**
     * 解析当前访问的URL, 为前端action
     */
    async loadRouterState() {
        /** @type {ActionRequest} action */
        const { action } = router.current;

        if (action) {
            this.mobileActionService.doAction(action).catch((msg) => {
                // rpc请求发生错误, 比如action不存在
                this.state.error = `error: ${msg}, actionReqeust: ${action}`;  // TODO: 错误处理目前只是在webclient展示一个div，后续可能需要封装为弹窗？
            });
        } else {
            // urlToState解析失败, 默认将其导向到`/home`
            this.mobileActionService.doAction("home");
        }
    };

    /**
     * 当 Ctrl 单击发生在 <a href> 元素中时，我们让浏览器执行默认行为，并且我们不希望任何其他侦听器执行, 从web/static/src/webclient/webclient.js拷贝过来
     *
     * @param {MouseEvent} ev
     */
    onGlobalClick(ev) {
        if (
            ev.ctrlKey
            && !ev.target.isContentEditable
            && ((ev.target instanceof HTMLAnchorElement && ev.target.href)
                || (ev.target instanceof HTMLElement && ev.target.closest("a[href]:not([href=''])")))
        ) {
            ev.stopImmediatePropagation();
            return;
        }
    }
}

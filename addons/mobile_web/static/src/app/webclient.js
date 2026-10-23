// owl
import { Component, xml, onMounted, onWillUnmount, proxy } from "@odoo/owl";

// odoo web core
import { localization } from "@web/core/data/l10n/localization";
import { useBus, useService } from "@web/core/utils/hooks";
import { routerBus } from "@web/core/services/browser/router";
import { router } from "@mobile_web/core/browser/router";

// webclient components
import { MobileActionContainer } from "@mobile_web/layout/action_container/action_container";
import { MobileNavBar } from "@mobile_web/layout/navbar/navbar";
import { MobileToast } from "@mobile_web/layout/toast/toast";
import { envOf } from "@mobile_web/core/env";


export class MobileWebClient extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileWebClient">
            <div class="m_webclient">
                <MobileNavBar/>
                <MobileActionContainer/>
                <MobileToast/>

                <!-- TODO: 错误处理目前只是在webclient展示一个div，后续可能需要封装为弹窗？ -->
                <t t-if="this.state.error">
                    <div t-esc="this.state.error" style="color: red;"/>
                </t>
            </div>
        </t>
    `;
    static components = {
        MobileNavBar,
        MobileActionContainer,
        MobileToast,
    };

    setup() {
        this.state = proxy({ error: /** @type {string|false} */ (false) });  // TODO: 错误处理目前只是在webclient展示一个div，后续可能需要封装为弹窗？
        this.mobileActionService = useService("mobileAction");
        this.localization = localization;

        // life cycle
        onMounted(() => {
            this.loadRouterState();
            envOf(this).bus.trigger("WEB_CLIENT_READY");
        });

        useBus(routerBus, "ROUTE_CHANGE", () => this.loadRouterState())
        this._onGlobalClick = this.onGlobalClick.bind(this);
        onMounted(() => window.addEventListener("click", this._onGlobalClick, { capture: true }));
        onWillUnmount(() => window.removeEventListener("click", this._onGlobalClick, { capture: true }));
    };

    /**
     * 解析当前访问的URL, 为前端action
     */
    async loadRouterState() {
        const { action } = /** @type {Record<string, any>} */ (router.current);

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
            && !(/** @type {HTMLElement} */ (ev.target)).isContentEditable
            && ((ev.target instanceof HTMLAnchorElement && ev.target.href)
                || (ev.target instanceof HTMLElement && ev.target.closest("a[href]:not([href=''])")))
        ) {
            ev.stopImmediatePropagation();
            return;
        }
    }
}

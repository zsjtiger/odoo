import { Component, onMounted, onWillUnmount, t, useProps, usePlugin, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { NotificationPlugin } from "@web/core/services/notifications/notification_plugin";

/** 默认自动关闭的时间; 与 web 的通知服务保持一致 */
const AUTOCLOSE_DELAY = 4000;

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
const TEXTS = {
    close: _t("Close"),
};

/**
 * 单条提示: 类型决定左侧颜色, 可选标题与操作按钮, 非持续显示的提示到时间后自动关闭
 */
export class MobileToastItem extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.MobileToastItem">
            <div t-attf-class="m_toast is_{{ this.notification.type }}" role="alert">
                <div class="m_toast_body">
                    <strong t-if="this.hasTitle" class="m_toast_title"><t t-esc="this.notification.title"/></strong>
                    <span class="m_toast_message"><t t-esc="this.notification.message"/></span>
                    <div t-if="this.buttons.length" class="m_toast_actions">
                        <button t-foreach="this.buttons" t-as="button" t-key="button_index" type="button"
                                class="m_toast_action" t-att-data-index="button_index" t-on-click="this.onButtonClick">
                            <t t-esc="button.name"/>
                        </button>
                    </div>
                </div>
                <button type="button" class="m_toast_close" t-att-aria-label="this.texts.close" t-on-click="this.onClose">×</button>
            </div>
        </t>
    `;
    props = useProps({ notification: t.object() });

    get notification() {
        return this.props.notification;
    }
    /** web 的通知默认没有按钮, 这里统一为数组 */
    get buttons() {
        return this.notification.buttons || [];
    }
    /** web 允许 title 为 true 表示使用默认标题, 这里只显示字符串或翻译对象 */
    get hasTitle() {
        const title = this.notification.title;
        return typeof title === "string" || (typeof title === "object" && title !== null);
    }

    setup() {
        let timer = null;
        onMounted(() => {
            if (!this.notification.sticky) {
                timer = setTimeout(() => this.notification.close(), this.notification.autocloseDelay ?? AUTOCLOSE_DELAY);
            }
        });
        onWillUnmount(() => clearTimeout(timer));
    }

    onClose() {
        this.notification.close();
    }

    onButtonClick(ev) {
        const button = this.buttons[Number(ev.currentTarget.dataset.index)];
        button.onClick();
    }
}

/**
 * 移动端的提示容器: 显示 web 通知服务中的全部提示, 位于底部标签栏上方
 */
export class MobileToast extends Component {
    static components = { MobileToastItem };
    static template = xml`
        <t t-name="mobile_web.MobileToast">
            <div class="m_toasts" aria-live="polite">
                <MobileToastItem t-foreach="this.notificationPlugin.notifications.items()" t-as="item" t-key="item.id" notification="item.props"/>
            </div>
        </t>
    `;
    notificationPlugin = usePlugin(NotificationPlugin);
}

import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 确认对话框 (iOS 风格的居中提示): 消息在上, 底部左侧为取消, 右侧为确认.
 * 危险操作的确认按钮使用红色.
 *
 * 视图中使用 useConfirmSheet(): ask(message) 返回 Promise<boolean>, 模板中放置 ConfirmSheet
 * 并把 answer 作为 onAnswer 传入; 用户选择后 Promise 才会完成.
 */
export class ConfirmSheet extends Component {
    fieldTexts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.ConfirmSheet">
            <div class="m_alert_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_alert" role="alertdialog" aria-modal="true">
                    <p class="m_alert_message"><t t-esc="this.props.message"/></p>
                    <div class="m_alert_footer">
                        <button type="button" class="m_alert_btn m_confirm_no" t-on-click="this.onCancel"><t t-esc="this.fieldTexts.cancel"/></button>
                        <button type="button" t-attf-class="m_alert_btn m_confirm_yes {{ this.props.danger ? 'is_danger' : 'is_primary' }}"
                                t-on-click="this.onConfirm"><t t-esc="this.props.confirmLabel"/></button>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        message: t.string(),
        confirmLabel: t.string().optional(""),
        danger: t.boolean().optional(false),
        onAnswer: t.function(),
    });

    onConfirm = () => {
        this.props.onAnswer(true);
    };
    onCancel = () => {
        this.props.onAnswer(false);
    };
    onBackdropClick(ev) {
        // 点击遮罩等同于取消; 点击对话框本身不关闭
        if (ev.target === ev.currentTarget) {
            this.props.onAnswer(false);
        }
    }
}

/**
 * 视图使用的确认状态: state.dialog 不为空时模板中显示 ConfirmSheet
 *
 * @returns {{state: {dialog: null | {message: string, confirmLabel: string, danger: boolean}}, ask: Function, answer: Function}}
 */
export function useConfirmSheet() {
    const state = proxy({ dialog: null });
    let resolver = null;

    // 作为子组件的回调传递, 使用箭头函数保持 this
    const ask = (message, options = {}) =>
        new Promise((resolve) => {
            // 同一时间只显示一个确认; 如果上一个还未回答, 视为取消
            resolver?.(false);
            resolver = resolve;
            state.dialog = {
                message,
                confirmLabel: options.confirmLabel || _t("Confirm"),
                danger: Boolean(options.danger),
            };
        });

    const answer = (value) => {
        const done = resolver;
        resolver = null;
        state.dialog = null;
        done?.(value);
    };

    return { state, ask, answer };
}

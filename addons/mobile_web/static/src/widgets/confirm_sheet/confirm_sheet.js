import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 对话框 (iOS 风格的居中提示), 内容可以定制:
 *  - message: 顶部的文字
 *  - component / componentProps: 自定义的正文组件, 收到的 props 为 componentProps 加上 close(value)
 *  - choices: 纵向排列的选项按钮 [{key, label, danger?}], 点击后返回 key (字符串)
 *  - 底部左侧为取消 (返回 false), 右侧为确认 (返回 true); 未设置 confirmLabel 时不显示确认按钮
 *
 * 视图中使用 useConfirmSheet(): ask(message, options) 返回 Promise, 模板中放置
 * <ConfirmSheet t-if="..." t-props="this.confirmSheet.state.dialog" onAnswer="this.confirmSheet.answer"/>.
 */
export class ConfirmSheet extends Component {
    fieldTexts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.ConfirmSheet">
            <div class="m_alert_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_alert" role="alertdialog" aria-modal="true">
                    <p t-if="this.props.message" class="m_alert_message"><t t-esc="this.props.message"/></p>
                    <div t-if="this.props.component" class="m_alert_body">
                        <t t-component="this.props.component" t-props="this.bodyProps"/>
                    </div>
                    <div t-if="this.props.choices.length" class="m_alert_choices">
                        <button t-foreach="this.props.choices" t-as="choice" t-key="choice.key" type="button"
                                t-attf-class="m_alert_choice {{ choice.danger ? 'is_danger' : '' }}"
                                t-att-data-key="choice.key" t-on-click="this.onChoice"><t t-esc="choice.label"/></button>
                    </div>
                    <div class="m_alert_footer">
                        <button type="button" class="m_alert_btn m_confirm_no" t-on-click="this.onCancel">
                            <t t-esc="this.props.cancelLabel or this.fieldTexts.cancel"/>
                        </button>
                        <button t-if="this.props.confirmLabel" type="button"
                                t-attf-class="m_alert_btn m_confirm_yes {{ this.props.danger ? 'is_danger' : 'is_primary' }}"
                                t-on-click="this.onConfirm"><t t-esc="this.props.confirmLabel"/></button>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        message: t.string().optional(""),
        component: t.or([t.function(), t.boolean()]).optional(false),
        componentProps: t.object().optional({}),
        choices: t.array().optional([]),
        confirmLabel: t.string().optional(""),
        cancelLabel: t.string().optional(""),
        danger: t.boolean().optional(false),
        onAnswer: t.function(),
    });

    /** 自定义正文收到的 props: 调用方给定的 props 加上 close(value) */
    get bodyProps() {
        return { ...this.props.componentProps, close: this.props.onAnswer };
    }

    onChoice(ev) {
        this.props.onAnswer(ev.currentTarget.dataset.key);
    }
    // 作为子组件的回调传递, 使用箭头函数保持 this
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
 * 视图使用的对话框状态: state.dialog 不为空时模板中显示 ConfirmSheet
 *
 * @returns {{state: {dialog: null | Object}, ask: Function, answer: Function}}
 */
export function useConfirmSheet() {
    const state = proxy({ dialog: null });
    let resolver = null;

    /**
     * @param {string} message
     * @param {{ confirmLabel?: string, danger?: boolean, cancelLabel?: string,
     *           choices?: {key: string, label: string, danger?: boolean}[],
     *           component?: Function, componentProps?: Object }} [options]
     * @returns {Promise<any>} 确认 true, 取消 false, 选项为其 key, 自定义正文调用 close(value) 的值
     */
    // 作为子组件的回调传递, 使用箭头函数保持 this
    const ask = (message, options = {}) =>
        new Promise((resolve) => {
            // 同一时间只显示一个对话框; 如果上一个还未回答, 视为取消
            resolver?.(false);
            resolver = resolve;
            const choices = options.choices || [];
            state.dialog = {
                message,
                choices,
                component: options.component || false,
                componentProps: options.componentProps || {},
                // 只有选项、没有确认按钮的对话框不显示确认
                confirmLabel: options.confirmLabel ?? (choices.length ? "" : _t("Confirm")),
                cancelLabel: options.cancelLabel || "",
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

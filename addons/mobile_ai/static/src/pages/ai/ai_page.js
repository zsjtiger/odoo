import { markup, onWillStart, proxy, xml } from "@odoo/owl";
import { Thread } from "@mail/core/common/thread";
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { Unavailable } from "@mobile_web/pages/shared/components/unavailable";
import { isModelAvailable } from "@mobile_web/pages/shared/data/model_access";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/data/l10n/translation";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    title: _t("AI"),
    empty: _t("Ask a question about your Odoo data"),
    placeholder: _t("Message AI"),
    send: _t("Send"),
    newChat: _t("New chat"),
    thinking: _t("Thinking…"),
    sendFailed: _t("Failed to send, please try again"),
    channelTitle: _t("AI chat"),
};

/** AI 助手: 需要安装 ai 模块 */
const MODEL = "ai.composer";
// 与网页端的 AI 聊天入口使用同一个界面标识, 因此会使用相同的智能体和工具
const INTERFACE_KEY = "systray_ai_button";
// 当前浏览器记住的会话 (仅是便利功能, 会话本身保存在服务端)
const STORAGE_KEY = "mobile_ai.channel_id";

function readStoredChannelId() {
    try {
        return Number(window.localStorage.getItem(STORAGE_KEY)) || null;
    } catch {
        return null;
    }
}

function storeChannelId(id) {
    try {
        window.localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
        // 无法保存时只是下次打开时开始新会话
    }
}

function toHtml(text) {
    const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<p>${escaped}</p>`;
}

/**
 * AI: 与网页端相同的会话. 消息由邮件的线程组件显示, 发送时走与网页端相同的
 * 消息发送流程 (由 ai 模块的线程补丁触发 AI 回复), 因此两端的聊天记录一致.
 */
export class AIPage extends MobilePage {
    texts = TEXTS;
    static components = { Thread, Unavailable };
    orm = useService("orm");
    store = useService("mail.store");
    state = proxy({ available: null, channel: null, draft: "", error: false });

    static template = xml`
        <t t-name="mobile_ai.AIPage">
            <div class="m_page m_ai_page">
                <div class="m_ai_header">
                    <strong><t t-esc="this.texts.title"/></strong>
                    <button type="button" class="m_ai_new_chat btn btn-link" t-on-click="this.newChat" t-if="this.state.channel">
                        <t t-esc="this.texts.newChat"/>
                    </button>
                </div>
                <Unavailable t-if="this.state.available === false"/>
                <div t-elif="this.state.channel" class="m_ai_body">
                    <div class="m_ai_thread">
                        <Thread thread="this.state.channel"/>
                    </div>
                    <div t-if="this.state.channel.isAiGenerating" class="m_ai_pending"><t t-esc="this.texts.thinking"/></div>
                    <p t-if="this.state.error" class="m_error"><t t-esc="this.texts.sendFailed"/></p>
                    <form class="m_ai_composer" t-on-submit.prevent="this.send">
                        <textarea class="m_ai_input" rows="1" t-att-placeholder="this.texts.placeholder"
                                  t-att-value="this.state.draft" t-on-input="this.onInput" t-on-keydown="this.onKeydown"/>
                        <button type="submit" class="m_ai_send btn btn-primary"
                                t-att-disabled="!this.state.draft.trim() or this.state.channel.isAiGenerating">
                            <t t-esc="this.texts.send"/>
                        </button>
                    </form>
                </div>
            </div>
        </t>
    `;

    setup() {
        onWillStart(async () => {
            this.state.available = await isModelAvailable(this.orm, MODEL);
            if (this.state.available) {
                this.state.channel = await this.openChannel();
            }
        });
    }

    /** 继续上次的会话; 没有或已不存在时新建一个 */
    async openChannel() {
        const storedId = readStoredChannelId();
        if (storedId) {
            const channel = await this.store["discuss.channel"].getOrFetch(storedId);
            if (channel) {
                return channel;
            }
        }
        return this.createChannel();
    }

    async createChannel() {
        const result = await this.orm.call(
            "ai.agent",
            "action_launch_ai_chat",
            [INTERFACE_KEY, false, false, this.texts.channelTitle, false, false, false]
        );
        this.store.insert(result.data);
        const channel = await this.store["discuss.channel"].getOrFetch(result.ai_channel_id);
        storeChannelId(channel.id);
        return channel;
    }

    async newChat() {
        this.state.error = false;
        this.state.channel = await this.createChannel();
    }

    onInput(ev) {
        this.state.draft = ev.target.value;
    }

    /** 回车发送, Shift+回车换行 */
    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const text = this.state.draft.trim();
        if (!text || this.state.channel.isAiGenerating) {
            return;
        }
        this.state.draft = "";
        this.state.error = false;
        try {
            await this.state.channel.post(markup(toHtml(text)));
        } catch {
            this.state.error = true;
        }
    }
}

mobilePageRegistry.add(PAGE_KEYS.AI, AIPage);

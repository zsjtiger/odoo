import { onWillStart, onWillUnmount, proxy, signal, xml } from "@odoo/owl";
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { Unavailable } from "@mobile_web/pages/shared/components/unavailable";
import { isModelAvailable } from "@mobile_web/pages/shared/data/model_access";
import { rpc } from "@web/core/services/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/data/l10n/translation";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    title: _t("AI"),
    empty: _t("Ask a question about your Odoo data"),
    placeholder: _t("Message AI"),
    send: _t("Send"),
    thinking: _t("Thinking…"),
    emptyAnswer: _t("No answer"),
    askFailed: _t("Failed to get an answer, please try again"),
};

/** AI 助手: 需要安装 ai 模块 */
const MODEL = "ai.composer";
const ASK_URL = "/mobile_web/ai/ask";

let nextMessageId = 1;

/**
 * AI: 手机端的单轮问答. 对话记录保存在页面中, 每次提问时把最近几轮一起发给服务端.
 */
export class AIPage extends MobilePage {
    texts = TEXTS;
    static components = { Unavailable };
    orm = useService("orm");
    state = proxy({ available: null, messages: [], draft: "", loading: false, error: false });
    messages = signal.ref();

    static template = xml`
        <t t-name="mobile_web.AIPage">
            <div class="m_page m_ai_page">
                <strong><t t-esc="this.texts.title"/></strong>
                <Unavailable t-if="this.state.available === false"/>
                <div t-elif="this.state.available" class="m_ai_body">
                    <div class="m_ai_messages" t-ref="this.messages">
                        <p t-if="!this.state.messages.length" class="m_empty"><t t-esc="this.texts.empty"/></p>
                        <div t-foreach="this.state.messages" t-as="message" t-key="message.id"
                             t-attf-class="m_ai_message m_ai_message_{{ message.role }}"><t t-esc="message.text"/></div>
                        <div t-if="this.state.loading" class="m_ai_message m_ai_message_assistant m_ai_pending"><t t-esc="this.texts.thinking"/></div>
                    </div>
                    <p t-if="this.state.error" class="m_error"><t t-esc="this.texts.askFailed"/></p>
                    <form class="m_ai_composer" t-on-submit.prevent="this.send">
                        <textarea class="m_ai_input" rows="1" t-att-placeholder="this.texts.placeholder"
                                  t-att-value="this.state.draft" t-on-input="this.onInput" t-on-keydown="this.onKeydown"/>
                        <button type="submit" class="m_ai_send btn btn-primary"
                                t-att-disabled="!this.state.draft.trim() or this.state.loading">
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
        });
        onWillUnmount(() => {
            this.unmounted = true;
        });
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
        const prompt = this.state.draft.trim();
        if (!prompt || this.state.loading) {
            return;
        }
        const history = this.state.messages.map(({ role, text }) => ({ role, text }));
        this.addMessage("user", prompt);
        this.state.draft = "";
        this.state.error = false;
        this.state.loading = true;
        try {
            const result = await rpc(ASK_URL, { prompt, history });
            this.addMessage("assistant", result.text || this.texts.emptyAnswer);
        } catch {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    addMessage(role, text) {
        this.state.messages.push({ id: nextMessageId++, role, text });
        requestAnimationFrame(() => {
            const el = this.messages();
            if (!this.unmounted && el) {
                el.scrollTop = el.scrollHeight;
            }
        });
    }
}

mobilePageRegistry.add(PAGE_KEYS.AI, AIPage);

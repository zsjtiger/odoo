import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { AIPage } from "@mobile_web/pages/ai/ai_page";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

/** 模拟模块是否安装: ir.model 中是否存在 ai.composer */
function aiInstalled(installed) {
    onRpc("ir.model", "search_count", () => (installed ? 1 : 0));
}

/** 在输入框中输入文字 (触发 t-model 的 input 事件) */
function typeQuestion(text) {
    const input = queryOne(".m_ai_input");
    input.value = text;
    input.dispatchEvent(new Event("input"));
}

test("the AI page shows the not-open placeholder when the AI module is not installed", async () => {
    aiInstalled(false);
    await mountWithCleanup(AIPage);
    await settle();
    expect(queryAll(".m_unavailable").length).toBe(1);
    expect(queryAll(".m_ai_input").length).toBe(0);
});

test("the send button stays disabled until a question is typed", async () => {
    aiInstalled(true);
    await mountWithCleanup(AIPage);
    await settle();
    expect(queryOne(".m_ai_send").disabled).toBe(true);
    typeQuestion("How many customers?");
    await settle();
    expect(queryOne(".m_ai_send").disabled).toBe(false);
});

test("a question is sent with the conversation so far and the answer is shown", async () => {
    aiInstalled(true);
    onRpc("/mobile_web/ai/ask", async (request) => {
        const { params } = await request.json();
        expect.step(JSON.stringify(params));
        return { text: "Three customers in New Jersey." };
    });
    await mountWithCleanup(AIPage);
    await settle();

    typeQuestion("Any customer in New Jersey?");
    await settle();
    await click(".m_ai_send");
    await settle();

    expect(queryAll(".m_ai_message_user")).toHaveText("Any customer in New Jersey?");
    expect(queryOne(".m_ai_message_assistant")).toHaveText("Three customers in New Jersey.");
    expect(queryOne(".m_ai_input")).toHaveValue("");

    typeQuestion("And in Texas?");
    await settle();
    await click(".m_ai_send");
    await settle();
    expect(queryAll(".m_ai_message").length).toBe(4);
    expect.verifySteps([
        JSON.stringify({ prompt: "Any customer in New Jersey?", history: [] }),
        JSON.stringify({
            prompt: "And in Texas?",
            history: [
                { role: "user", text: "Any customer in New Jersey?" },
                { role: "assistant", text: "Three customers in New Jersey." },
            ],
        }),
    ]);
});

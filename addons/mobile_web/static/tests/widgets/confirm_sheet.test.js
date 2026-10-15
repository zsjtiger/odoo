import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { ConfirmSheet, useConfirmSheet } from "@mobile_web/widgets/confirm_sheet/confirm_sheet";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

/** 自定义正文: 显示 text, 点击后通过 close 作答 */
class CustomBody extends Component {
    static template = xml`
        <div class="custom-body">
            <span class="body-text"><t t-esc="this.props.text"/></span>
            <button class="body-close" t-on-click="this.onClose">close</button>
        </div>
    `;
    props = useProps({ text: t.string(), close: t.function() });
    onClose() {
        this.props.close("custom");
    }
}

test("the dialog shows the message and a danger confirm button on the right", async () => {
    await mountWithCleanup(ConfirmSheet, {
        props: { message: "Delete it?", confirmLabel: "Delete", danger: true, onAnswer: () => {} },
    });
    expect(queryOne(".m_alert_message")).toHaveText("Delete it?");
    expect(queryOne(".m_confirm_yes")).toHaveText("Delete");
    expect(queryOne(".m_confirm_yes")).toHaveClass("is_danger");
    expect(queryOne(".m_confirm_no")).toHaveText("Cancel");
});

test("confirming answers true and cancelling answers false", async () => {
    const answers = [];
    await mountWithCleanup(ConfirmSheet, {
        props: { message: "Sure?", confirmLabel: "Yes", onAnswer: (v) => answers.push(v) },
    });
    await click(".m_confirm_yes");
    await click(".m_confirm_no");
    expect(answers).toEqual([true, false]);
});

test("tapping the backdrop cancels, tapping the dialog does not", async () => {
    const answers = [];
    await mountWithCleanup(ConfirmSheet, {
        props: { message: "Sure?", confirmLabel: "Yes", onAnswer: (v) => answers.push(v) },
    });
    await click(".m_alert_message");
    expect(answers).toEqual([]);
    await click(".m_alert_backdrop");
    expect(answers).toEqual([false]);
});

test("choices are stacked above the footer and answer with their key", async () => {
    const answers = [];
    await mountWithCleanup(ConfirmSheet, {
        props: {
            message: "人在天边月上明，风初紧，吹入画帘旌",
            choices: [
                { key: "read", label: "在线阅读" },
                { key: "download", label: "下载文件" },
                { key: "remove", label: "删除", danger: true },
            ],
            onAnswer: (v) => answers.push(v),
        },
    });
    expect(queryAll(".m_alert_choice").map((el) => el.textContent)).toEqual(["在线阅读", "下载文件", "删除"]);
    expect(queryOne(".m_alert_choice:last-child")).toHaveClass("is_danger");
    await click('.m_alert_choice[data-key="download"]');
    expect(answers).toEqual(["download"]);
});

test("without a confirm label only the cancel button is shown", async () => {
    await mountWithCleanup(ConfirmSheet, {
        props: { message: "Pick one", choices: [{ key: "a", label: "A" }], onAnswer: () => {} },
    });
    expect(queryAll(".m_confirm_yes").length).toBe(0);
    expect(queryOne(".m_confirm_no")).toHaveText("Cancel");
});

test("a custom body receives its props and can answer through close", async () => {
    const answers = [];
    await mountWithCleanup(ConfirmSheet, {
        props: {
            component: CustomBody,
            componentProps: { text: "hello" },
            onAnswer: (v) => answers.push(v),
        },
    });
    expect(queryOne(".body-text")).toHaveText("hello");
    await click(".body-close");
    expect(answers).toEqual(["custom"]);
});

class Host extends Component {
    static components = { ConfirmSheet };
    static template = xml`
        <div class="host">
            <button class="ask" t-on-click="this.onAsk">ask</button>
            <button class="ask-choices" t-on-click="this.onAskChoices">choices</button>
            <span class="result"><t t-esc="this.state.result"/></span>
            <ConfirmSheet t-if="this.confirm.state.dialog" t-props="this.confirm.state.dialog" onAnswer="this.confirm.answer"/>
        </div>
    `;
    confirm = useConfirmSheet();
    state = proxy({ result: "none" });
    onAsk = async () => {
        const yes = await this.confirm.ask("Really?", { confirmLabel: "Go", danger: true });
        this.state.result = String(yes);
    };
    onAskChoices = async () => {
        const key = await this.confirm.ask("Which?", {
            choices: [
                { key: "one", label: "One" },
                { key: "two", label: "Two" },
            ],
        });
        this.state.result = String(key);
    };
}

test("useConfirmSheet resolves a confirm with true", async () => {
    await mountWithCleanup(Host);
    await click(".ask");
    await settle();
    expect(queryOne(".m_alert_message")).toHaveText("Really?");
    await click(".m_confirm_yes");
    await settle();
    expect(queryAll(".m_alert").length).toBe(0);
    expect(queryOne(".result")).toHaveText("true");
});

test("useConfirmSheet resolves a choice with its key", async () => {
    await mountWithCleanup(Host);
    await click(".ask-choices");
    await settle();
    await click('.m_alert_choice[data-key="two"]');
    await settle();
    expect(queryOne(".result")).toHaveText("two");
});

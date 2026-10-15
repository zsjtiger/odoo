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

class Host extends Component {
    static components = { ConfirmSheet };
    static template = xml`
        <div class="host">
            <button class="ask" t-on-click="this.onAsk">ask</button>
            <span class="result"><t t-esc="this.result"/></span>
            <ConfirmSheet t-if="this.confirm.state.dialog" message="this.confirm.state.dialog.message"
                          confirmLabel="this.confirm.state.dialog.confirmLabel" danger="this.confirm.state.dialog.danger"
                          onAnswer="this.confirm.answer"/>
        </div>
    `;
    confirm = useConfirmSheet();
    state = proxy({ result: "none" });
    get result() {
        return this.state.result;
    }
    onAsk = async () => {
        const yes = await this.confirm.ask("Really?", { confirmLabel: "Go", danger: true });
        this.state.result = String(yes);
    };
}

test("useConfirmSheet resolves the ask with the user's answer", async () => {
    await mountWithCleanup(Host);
    await click(".ask");
    await settle();
    expect(queryOne(".m_alert_message")).toHaveText("Really?");
    await click(".m_confirm_yes");
    await settle();
    expect(queryAll(".m_alert").length).toBe(0);
    expect(queryOne(".result")).toHaveText("true");
});

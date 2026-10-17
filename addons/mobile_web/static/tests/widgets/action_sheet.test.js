import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { ActionSheet } from "@mobile_web/widgets/action_sheet/action_sheet";

describe.current.tags("mobile");

test("the sheet lists one item per action", async () => {
    await mountWithCleanup(ActionSheet, {
        props: {
            items: [
                { key: "a", label: "Confirm", run: () => {} },
                { key: "b", label: "Cancel order", run: () => {} },
            ],
            onClose: () => {},
        },
    });
    expect(queryAll(".m_sheet_item").map((el) => el.textContent)).toEqual(["Confirm", "Cancel order"]);
});

test("clicking an item runs it and then closes the sheet", async () => {
    const events = [];
    await mountWithCleanup(ActionSheet, {
        props: {
            items: [{ key: "a", label: "Confirm", run: async () => events.push("run") }],
            onClose: () => events.push("close"),
        },
    });
    await click(".m_sheet_item");
    expect(events).toEqual(["run", "close"]);
});

test("the sheet closes only after an asynchronous action has finished", async () => {
    const events = [];
    await mountWithCleanup(ActionSheet, {
        props: {
            items: [{ key: "a", label: "Slow", run: async () => {
                await new Promise((resolve) => setTimeout(resolve, 10));
                events.push("done");
            } }],
            onClose: () => events.push("close"),
        },
    });
    await click(".m_sheet_item");
    // click 不等待异步的操作完成, 等待其定时器结束
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(events).toEqual(["done", "close"]);
});

test("the cancel button and the backdrop close the sheet", async () => {
    let closed = 0;
    await mountWithCleanup(ActionSheet, {
        props: { items: [], onClose: () => closed++ },
    });
    await click(".m_sheet_cancel");
    // 点击弹层内容不关闭, 只有点击遮罩本身才关闭
    queryOne(".m_sheet").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(closed).toBe(1);
    queryOne(".m_sheet_backdrop").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(closed).toBe(2);
});

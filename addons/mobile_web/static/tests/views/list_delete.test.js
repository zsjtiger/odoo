import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    _records = [
        { id: 1, name: "Alpha" },
        { id: 2, name: "Beta" },
    ];
}

defineModels([Partner]);

const FIELDS = { name: { type: "char", string: "Name" } };
const LIST_ARCH = `<list><field name="name" class="mobile_title"/></list>`;

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

function touch(el, type, x, y) {
    const point = new Touch({ identifier: 1, target: el, clientX: x, clientY: y });
    el.dispatchEvent(
        new TouchEvent(type, { touches: type === "touchend" ? [] : [point], changedTouches: [point], bubbles: true })
    );
}

/** 第一行的删除按钮 */
function firstDelete() {
    return queryAll(".m_swipe_delete")[0];
}

/** 左滑第一行露出删除按钮 */
async function swipeFirstRow() {
    const row = queryAll(".m_swipe_row")[0];
    touch(row, "touchstart", 200, 50);
    touch(row, "touchmove", 100, 50);
    touch(row, "touchend", 100, 50);
    await settle();
}

/**
 * 挂载列表, 并记录删除请求和列表的重新加载次数
 * @param {{ canDelete: boolean, arch?: string }} options
 */
async function mountList({ canDelete, arch = LIST_ARCH }) {
    const unlinked = [];
    let reads = 0;
    onRpc("res.partner", "has_access", () => canDelete);
    onRpc("res.partner", "unlink", ({ args }) => {
        unlinked.push(...args[0]);
        return true;
    });
    onRpc("res.partner", "web_search_read", () => {
        reads++;
    });
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    return { unlinked, reads: () => reads };
}

/** 在确认弹层中作答: 确认(危险按钮) 或取消 */
async function answerSheet(yes) {
    await click(yes ? ".m_confirm_yes" : ".m_confirm_no");
    await settle();
}

test("the delete asks for confirmation first and deletes only after the user confirms", async () => {
    const list = await mountList({ canDelete: true });
    const before = list.reads();
    await swipeFirstRow();
    await click(firstDelete());
    await settle();
    expect(queryOne(".m_alert_message")).toHaveText("Delete this record?");
    expect(list.unlinked).toEqual([]);
    await answerSheet(true);
    expect(list.unlinked).toEqual([1]);
    expect(list.reads()).toBe(before + 1);
});

test("cancelling the confirmation keeps the record", async () => {
    const list = await mountList({ canDelete: true });
    await swipeFirstRow();
    await click(firstDelete());
    await settle();
    await answerSheet(false);
    expect(queryAll(".m_alert").length).toBe(0);
    expect(list.unlinked).toEqual([]);
});

test("without delete access the delete button is unavailable and no confirmation is shown", async () => {
    const list = await mountList({ canDelete: false });
    await swipeFirstRow();
    expect(firstDelete()).toHaveAttribute("disabled");
    await click(firstDelete());
    await settle();
    expect(queryAll(".m_alert").length).toBe(0);
    expect(list.unlinked).toEqual([]);
});

test("delete=\"0\" in the arch disables deleting even with access", async () => {
    const list = await mountList({ canDelete: true, arch: `<list delete="0"><field name="name"/></list>` });
    await swipeFirstRow();
    expect(firstDelete()).toHaveAttribute("disabled");
    await click(firstDelete());
    await settle();
    expect(queryAll(".m_alert").length).toBe(0);
    expect(list.unlinked).toEqual([]);
});

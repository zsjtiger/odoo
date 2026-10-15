import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { MobileListView } from "@mobile_web/views/list/mobile_list_view";

describe.current.tags("mobile");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    _records = [{ id: 1, name: "Alpha" }];
}

defineModels([Partner]);

const FIELDS = { name: { type: "char", string: "Name" } };
const LIST_ARCH = `<list><field name="name" class="mobile_title"/></list>`;

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

/** 派发一个触摸事件; 手指位于 y 像素处 */
function touch(el, type, y) {
    const point = new Touch({ identifier: 1, target: el, clientX: 0, clientY: y });
    el.dispatchEvent(
        new TouchEvent(type, {
            touches: type === "touchend" ? [] : [point],
            changedTouches: [point],
            bubbles: true,
        })
    );
}

/** 从 startY 下拉到 endY 并松开 */
async function pullDown(el, startY, endY) {
    touch(el, "touchstart", startY);
    touch(el, "touchmove", endY);
    await settle();
}

async function release(el) {
    touch(el, "touchend", 0);
    await settle();
}

async function mountList() {
    let reads = 0;
    onRpc("res.partner", "web_search_read", () => {
        reads++;
    });
    await mountWithCleanup(MobileListView, {
        props: { resModel: "res.partner", arch: LIST_ARCH, fields: FIELDS, domain: [], context: {}, onSelect: () => {} },
    });
    await settle();
    return { el: queryOne(".m_list_view"), reads: () => reads };
}

test("pulling past the threshold and releasing reloads the list", async () => {
    const list = await mountList();
    const before = list.reads();
    await pullDown(list.el, 100, 220);
    await release(list.el);
    expect(list.reads()).toBe(before + 1);
});

test("a short pull does not reload the list", async () => {
    const list = await mountList();
    const before = list.reads();
    await pullDown(list.el, 100, 140);
    await release(list.el);
    expect(list.reads()).toBe(before);
});

test("the indicator asks to release once the pull passes the threshold", async () => {
    const list = await mountList();
    expect(queryAll(".m_pull_indicator").length).toBe(0);
    await pullDown(list.el, 100, 220);
    expect(queryOne(".m_pull_indicator")).toHaveText("Release to refresh");
    await release(list.el);
    expect(queryAll(".m_pull_indicator").length).toBe(0);
});

test("a short pull shows the hint to pull and then hides", async () => {
    const list = await mountList();
    await pullDown(list.el, 100, 140);
    expect(queryOne(".m_pull_indicator")).toHaveText("Pull to refresh");
    await release(list.el);
    expect(queryAll(".m_pull_indicator").length).toBe(0);
});

test("the list has no refresh button and no sort menu of its own: sorting is in the search bar", async () => {
    await mountList();
    expect(queryAll(".m_link_button").length).toBe(0);
    expect(queryAll(".m_sort_menu_toggle").length).toBe(0);
});

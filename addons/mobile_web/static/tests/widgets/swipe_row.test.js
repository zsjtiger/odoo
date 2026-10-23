import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SwipeRow } from "@mobile_web/widgets/swipe_row/swipe_row";

describe.current.tags("mobile");

class Host extends Component {
    static components = { SwipeRow };
    static template = xml`
        <div class="host">
            <SwipeRow resId="7" disabled="this.props.disabled" label="'Delete'" onDelete="this.props.onDelete">
                <span class="content">row</span>
            </SwipeRow>
        </div>
    `;
    props = useProps({ disabled: t.boolean().optional(false), onDelete: t.function() });
}

async function settle() {
    for (let i = 0; i < 6; i++) {
        await animationFrame();
    }
}

function touch(el, type, x, y) {
    const point = new Touch({ identifier: 1, target: el, clientX: x, clientY: y });
    el.dispatchEvent(
        new TouchEvent(type, { touches: type === "touchend" ? [] : [point], changedTouches: [point], bubbles: true })
    );
}

/** 在行上从 (x0, y0) 拖到 (x1, y1) 并松开 */
async function drag(x0, y0, x1, y1) {
    const row = queryOne(".m_swipe_row");
    touch(row, "touchstart", x0, y0);
    touch(row, "touchmove", x1, y1);
    touch(row, "touchend", x1, y1);
    await settle();
}

function offset() {
    const style = queryOne(".m_swipe_content").getAttribute("style") || "";
    const match = style.match(/translateX\((-?\d+(\.\d+)?)px\)/);
    return match ? Number(match[1]) : 0;
}

test("dragging left past half the delete width keeps the row open", async () => {
    await mountWithCleanup(Host, { props: { onDelete: () => {} } });
    await drag(200, 50, 100, 50);
    expect(offset()).toBe(-72);
});

test("a short drag left closes again on release", async () => {
    await mountWithCleanup(Host, { props: { onDelete: () => {} } });
    await drag(200, 50, 170, 50);
    expect(offset()).toBe(0);
});

test("a vertical drag scrolls the page and does not reveal the delete button", async () => {
    await mountWithCleanup(Host, { props: { onDelete: () => {} } });
    await drag(100, 200, 98, 60);
    expect(offset()).toBe(0);
});

test("tapping the row while it is open closes it without opening the record", async () => {
    const deleted = [];
    await mountWithCleanup(Host, { props: { onDelete: (id) => deleted.push(id) } });
    await drag(200, 50, 100, 50);
    await click(".content");
    await settle();
    expect(offset()).toBe(0);
    expect(deleted.length).toBe(0);
});

test("tapping the delete button calls onDelete with the record id", async () => {
    const deleted = [];
    await mountWithCleanup(Host, { props: { onDelete: (id) => deleted.push(id) } });
    await drag(200, 50, 100, 50);
    await click(".m_swipe_delete");
    await settle();
    expect(deleted).toEqual([7]);
    expect(offset()).toBe(0);
});

test("a disabled delete button is shown but cannot delete", async () => {
    const deleted = [];
    await mountWithCleanup(Host, { props: { disabled: true, onDelete: (id) => deleted.push(id) } });
    await drag(200, 50, 100, 50);
    expect(queryOne(".m_swipe_delete")).toHaveAttribute("disabled");
    await click(".m_swipe_delete");
    await settle();
    expect(deleted.length).toBe(0);
    expect(queryAll(".m_swipe_delete").length).toBe(1);
});

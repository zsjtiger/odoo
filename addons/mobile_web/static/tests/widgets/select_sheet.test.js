import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { MobileSelectSheet } from "@mobile_web/widgets/select_sheet/select_sheet";

describe.current.tags("mobile");

const OPTIONS = [
    { id: 1, name: "Apple" },
    { id: 2, name: "Banana" },
];

test("MobileSelectSheet lists the options and confirms a single pick", async () => {
    const picked = [];
    await mountWithCleanup(MobileSelectSheet, {
        props: {
            title: "Fruit",
            options: OPTIONS,
            onConfirm: (selected) => picked.push(selected),
            onClose: () => {},
        },
    });
    expect(queryAll(".m_sheet_item").length).toBe(2);
    await click(queryAll(".m_sheet_item")[1]);
    expect(picked).toEqual([[{ id: 2, name: "Banana" }]]);
});

test("MobileSelectSheet multi-select confirms every checked option", async () => {
    const picked = [];
    await mountWithCleanup(MobileSelectSheet, {
        props: {
            title: "Fruit",
            options: OPTIONS,
            multiple: true,
            selected: [{ id: 1, name: "Apple" }],
            onConfirm: (selected) => picked.push(selected),
            onClose: () => {},
        },
    });
    await click(queryAll(".m_sheet_item")[1]);
    await click(".m_sheet_btn_primary");
    expect(picked[0].map((o) => o.id)).toEqual([1, 2]);
});

test("MobileSelectSheet close button calls onClose", async () => {
    let closed = false;
    await mountWithCleanup(MobileSelectSheet, {
        props: {
            title: "Fruit",
            options: OPTIONS,
            onConfirm: () => {},
            onClose: () => (closed = true),
        },
    });
    await click(".m_sheet_btn");
    expect(closed).toBe(true);
});

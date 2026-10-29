import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { MobileFilterSheet } from "@mobile_web/widgets/filter_sheet/filter_sheet";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

const SECTIONS = [
    {
        name: "mine",
        label: "Subordinates",
        options: [{ key: "mine", label: "Only mine", radio: true }],
        cards: { field: "user_id", records: [{ id: 7, name: "Ann", sub: "ann@example.com" }] },
    },
    {
        name: "speaker",
        label: "Speaker",
        options: [
            { key: "yes", label: "Speaker" },
            { key: "no", label: "Non-speaker" },
        ],
        cards: null,
    },
];

function props(overrides = {}) {
    return {
        title: "Filter",
        sections: SECTIONS,
        selected: { options: [], cards: {} },
        onConfirm: () => {},
        onClose: () => {},
        ...overrides,
    };
}

test("each section shows its title, its options and its cards", async () => {
    await mountWithCleanup(MobileFilterSheet, { props: props() });
    await settle();
    expect(queryAll(".m_filter_title").map((el) => el.textContent)).toEqual(["Subordinates", "Speaker"]);
    expect(queryAll(".m_filter_radio").length).toBe(1);
    expect(queryAll(".m_filter_chip").length).toBe(2);
    expect(queryAll(".m_filter_card").length).toBe(1);
    expect(queryOne(".m_filter_card_sub").textContent).toBe("ann@example.com");
});

test("confirm reports the chosen options and cards", async () => {
    const results = [];
    await mountWithCleanup(MobileFilterSheet, { props: props({ onConfirm: (value) => results.push(value) }) });
    await settle();
    await click(".m_filter_radio");
    await click(".m_filter_chip[data-key='no']");
    await click(".m_filter_card");
    await settle();
    await click(".m_sheet_btn_primary");
    await settle();
    expect(results).toEqual([{ options: ["mine", "no"], cards: { user_id: [7] } }]);
});

test("a chip toggles off when it is pressed again", async () => {
    const results = [];
    await mountWithCleanup(MobileFilterSheet, { props: props({ onConfirm: (value) => results.push(value) }) });
    await settle();
    await click(".m_filter_chip[data-key='yes']");
    await click(".m_filter_chip[data-key='yes']");
    await settle();
    await click(".m_sheet_btn_primary");
    await settle();
    expect(results).toEqual([{ options: [], cards: {} }]);
});

test("cancel closes without reporting anything", async () => {
    const results = [];
    let closed = 0;
    await mountWithCleanup(MobileFilterSheet, {
        props: props({ onConfirm: (value) => results.push(value), onClose: () => closed++ }),
    });
    await settle();
    await click(".m_filter_chip[data-key='yes']");
    await click(".m_sheet_btn:not(.m_sheet_btn_primary)");
    await settle();
    expect(results).toEqual([]);
    expect(closed).toBe(1);
});

import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { DashBoardCardWidget } from "@board/widget/dashboard_card/dashboard_card";

describe.current.tags("headless");

const DATA = [
    { name: "Sales", value: 1200, category: null, filter_domain: [["state", "=", "sale"]] },
    { name: "Quotes", value: 300, category: null, filter_domain: [["state", "=", "draft"]] },
    { name: "Refunds", value: 40, category: null, filter_domain: [["state", "=", "cancel"]] },
];

async function mountCards(options = {}) {
    await mountWithCleanup(DashBoardCardWidget, {
        props: {
            name: "dashboard",
            readonly: true,
            options,
            record: {
                data: { dashboard: JSON.stringify(DATA) },
                resModel: "sale.order",
                context: {},
                fields: { dashboard: { type: "text", string: "Dashboard" } },
            },
        },
    });
    await animationFrame();
}

test("each data item is a card with its name and value", async () => {
    await mountCards();
    const cards = queryAll(".snow_mdm_dashboard_card:not(.snow_mdm_dashboard_card_placeholder)");
    expect(cards.length).toBe(3);
    expect(cards[0].querySelector(".snow_mdm_dashboard_card_title").textContent).toBe("Sales");
});

test("with a column count the last row is filled with placeholders", async () => {
    await mountCards({ column: 2 });
    expect(queryAll(".snow_mdm_dashboard_card_placeholder").length).toBe(1);
});

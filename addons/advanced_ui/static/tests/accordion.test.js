import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, queryAll, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { Accordion } from "@advanced_ui/accordion/accordion";

describe.current.tags("desktop");

const items = [
    { id: "a", summary: "Accordion Summary", details: "Accordion details - A" },
    { id: "b", summary: "Accordion Summary B", details: "Accordion details - B" },
];

/**
 * Clicks the summary of the item at the given index, then waits for the re-render.
 * @param {number} index
 */
async function clickSummary(index) {
    await click(queryAll(".o_accordion_summary")[index]);
    await animationFrame();
}

test("accordion: all sections closed by default", async () => {
    await mountWithCleanup(Accordion, { props: { items } });
    expect(".o_accordion_item").toHaveCount(2);
    expect(".o_accordion_details").toHaveCount(0);
});

test("accordion: opening one section closes the other one", async () => {
    await mountWithCleanup(Accordion, { props: { items } });
    await clickSummary(0);
    expect(queryAllTexts(".o_accordion_details")).toEqual(["Accordion details - A"]);
    await clickSummary(1);
    expect(queryAllTexts(".o_accordion_details")).toEqual(["Accordion details - B"]);
    expect(".o_accordion_item_open").toHaveCount(1);
});

test("accordion: multiple sections can be open", async () => {
    await mountWithCleanup(Accordion, { props: { items, multiple: true } });
    await clickSummary(0);
    await clickSummary(1);
    expect(".o_accordion_details").toHaveCount(2);
    await clickSummary(0);
    expect(queryAllTexts(".o_accordion_details")).toEqual(["Accordion details - B"]);
});

test("accordion: open sections given at start", async () => {
    await mountWithCleanup(Accordion, { props: { items, openIds: ["b"] } });
    expect(queryOne(".o_accordion_details").textContent).toBe("Accordion details - B");
    expect(queryAll(".o_accordion_summary")[1]).toHaveAttribute("aria-expanded", "true");
});

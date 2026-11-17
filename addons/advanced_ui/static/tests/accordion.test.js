import { Component, xml } from "@odoo/owl";
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

test("accordion: slot content is rendered inside the open section", async () => {
    class Wrapper extends Component {
        static components = { Accordion };
        static template = xml`
            <Accordion items="this.sections" openIds="['a']">
                <t t-set-slot="details" t-slot-scope="scope">
                    <span class="o_custom_field" t-out="scope.item.id"/>
                    <div class="o_accordion_wide o_custom_list" t-if="scope.item.id === 'a'">list</div>
                </t>
            </Accordion>`;
        setup() {
            this.sections = items;
        }
    }
    await mountWithCleanup(Wrapper);
    expect(".o_accordion_group").toHaveCount(1);
    expect(".o_accordion_group .o_custom_field").toHaveText("a");
    expect(".o_accordion_group .o_custom_list").toHaveCount(1);
    expect(".o_accordion_wide").toHaveCount(1);
});

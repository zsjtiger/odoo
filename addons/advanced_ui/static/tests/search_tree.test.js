import { describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { defineModels, fields, models, mountView } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Category extends models.Model {
    name = fields.Char();
    parent_id = fields.Many2one({ relation: "category" });

    _records = [
        { id: 1, name: "Regions", parent_id: false },
        { id: 2, name: "Asia", parent_id: 1 },
        { id: 3, name: "Europe", parent_id: 1 },
        { id: 4, name: "Japan", parent_id: 2 },
        { id: 5, name: "VIP", parent_id: false },
    ];
}

class Item extends models.Model {
    name = fields.Char();
    category_id = fields.Many2one({ relation: "category" });

    _records = [
        { id: 1, name: "Tokyo", category_id: 4 },
        { id: 2, name: "Paris", category_id: 3 },
        { id: 3, name: "HQ", category_id: 5 },
    ];
    _views = {
        list: /* xml */ `<list><field name="name"/></list>`,
        search: /* xml */ `
            <search>
                <searchpanel>
                    <field name="category_id" expand="1" limit="3" tree_parent="parent_id" tree_label="name"/>
                </searchpanel>
            </search>`,
    };
}

defineModels([Category, Item]);

/** The header of the tree node with the given label. */
function nodeHeader(label) {
    return [...document.querySelectorAll(".o_search_panel_category_value_header")].find(
        (header) => header.innerText.trim() === label
    );
}

test("the tree shows the first page of nodes, and a Load more button", async () => {
    await mountView({ type: "list", resModel: "item" });
    const labels = queryAllTexts(".o_search_panel_label_title");
    expect(labels).toInclude("Regions");
    expect(labels).not.toInclude("VIP");
    expect(".o_search_tree_more_button").toHaveCount(1);
});

test("Load more shows the next page of nodes", async () => {
    await mountView({ type: "list", resModel: "item" });
    await click(".o_search_tree_more_button");
    expect(queryAllTexts(".o_search_panel_label_title")).toInclude("VIP");
    expect(".o_search_tree_more_button").toHaveCount(0);
});

test("selecting a node filters on the node and its descendants", async () => {
    await mountView({ type: "list", resModel: "item" });
    await click(".o_search_tree_more_button");
    await click(nodeHeader("Regions"));
    // Tokyo is under Japan, under Asia; Paris is under Europe; HQ is under VIP only
    expect(queryAllTexts(".o_data_row .o_data_cell")).toEqual(["Tokyo", "Paris"]);
});

test("selecting the All node shows every record", async () => {
    await mountView({ type: "list", resModel: "item" });
    await click(".o_search_tree_more_button");
    await click(nodeHeader("Regions"));
    await click(nodeHeader("All"));
    expect(queryAllTexts(".o_data_row .o_data_cell")).toEqual(["Tokyo", "Paris", "HQ"]);
});

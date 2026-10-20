import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, queryAllTexts } from "@odoo/hoot-dom";
import { defineModels, fields, models, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { TreeNav } from "@advanced_ui/tree_form/tree_form";

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

defineModels([Category]);

/** The node of the tree with the given label. */
function nodeOf(label) {
    return [...document.querySelectorAll(".o_tree_nav_node")].find(
        (node) => node.querySelector(".o_tree_nav_label").innerText.trim() === label
    );
}

/** Mounts the tree of the categories, with the given page size and selection. */
function mountTree(props = {}) {
    return mountWithCleanup(TreeNav, {
        props: {
            resModel: "category",
            parentField: "parent_id",
            labelField: "name",
            context: {},
            selectedId: false,
            onSelect: (id) => expect.step(id),
            ...props,
        },
    });
}

test("the roots and their children are shown, and the children of a node are hidden until it opens", async () => {
    await mountTree();
    // Regions and VIP are roots; the first level is open, so Asia and Europe show
    expect(queryAllTexts(".o_tree_nav_label")).toEqual(["Regions", "Asia", "Europe", "VIP"]);
});

test("a node opens and closes its children", async () => {
    await mountTree();
    expect(queryAllTexts(".o_tree_nav_label")).not.toInclude("Japan");
    await click(nodeOf("Asia").querySelector(".o_tree_nav_toggle"));
    await animationFrame();
    expect(queryAllTexts(".o_tree_nav_label")).toInclude("Japan");
    await click(nodeOf("Asia").querySelector(".o_tree_nav_toggle"));
    await animationFrame();
    expect(queryAllTexts(".o_tree_nav_label")).not.toInclude("Japan");
});

test("clicking a node selects it", async () => {
    await mountTree();
    expect.verifySteps([]);
    await click(nodeOf("Europe"));
    expect.verifySteps([3]);
});

test("Load more reads the next page of nodes, until there are none", async () => {
    await mountTree({ limit: 2 });
    expect(queryAllTexts(".o_tree_nav_label")).not.toInclude("Europe");
    // Each page adds `limit` nodes: the second page holds Europe and Japan
    await click(".o_tree_nav_more_button");
    await animationFrame();
    expect(queryAllTexts(".o_tree_nav_label")).toInclude("Europe");
    expect(queryAllTexts(".o_tree_nav_label")).not.toInclude("VIP");
    // The third page holds VIP, and there is no page after it
    await click(".o_tree_nav_more_button");
    await animationFrame();
    expect(queryAllTexts(".o_tree_nav_label")).toInclude("VIP");
    expect(".o_tree_nav_more_button").toHaveCount(0);
});

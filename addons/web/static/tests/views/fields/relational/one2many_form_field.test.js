import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { clickSave, contains, defineModels, fields, models, mountView } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

class KeyInfo extends models.Model {
    _name = "keyinfo";
    product = fields.Char();
    feedback = fields.Selection({
        selection: [
            ["positive", "Positive"],
            ["neutral", "Neutral"],
        ],
    });
    item_id = fields.Many2one({ relation: "keyitem" });
    _records = [
        { id: 1, product: "测试", feedback: "positive", item_id: 1 },
        { id: 2, product: "鼓翘颗粒", feedback: "neutral", item_id: 1 },
    ];
}

class KeyItem extends models.Model {
    _name = "keyitem";
    name = fields.Char();
    keyinfo_ids = fields.One2many({ relation: "keyinfo", inverse_name: "item_id" });
    _records = [{ id: 1, name: "Alpha", keyinfo_ids: [1, 2] }];
}

defineModels([KeyInfo, KeyItem]);

const ARCH = `
    <form>
        <field name="name"/>
        <field name="keyinfo_ids" widget="one2many_form">
            <list editable="bottom">
                <field name="product"/>
                <field name="feedback"/>
            </list>
        </field>
    </form>
`;

async function mountItem(arch = ARCH) {
    await mountView({ type: "form", resModel: "keyitem", resId: 1, arch });
    await animationFrame();
}

/** 卡片中的字段标签 */
function cardLabels(index) {
    return [...queryAll(".o_one2many_form_card")[index].querySelectorAll("span.text-muted")].map((el) => el.textContent);
}

test("each line is a card showing the columns of the list view", async () => {
    await mountItem();
    expect(queryAll(".o_one2many_form_card").length).toBe(2);
    expect(cardLabels(0)).toEqual(["Product", "Feedback"]);
    expect(queryAll(".o_one2many_form_card input")[0]).toHaveValue("测试");
});

test("the plus button adds an empty card", async () => {
    await mountItem();
    await click(".o_one2many_form_add");
    await animationFrame();
    expect(queryAll(".o_one2many_form_card").length).toBe(3);
});

test("the close button removes the line, saved as a delete", async () => {
    await mountItem();
    await click(queryAll(".o_one2many_form_card .btn-close")[0]);
    await animationFrame();
    expect(queryAll(".o_one2many_form_card").length).toBe(1);
    await clickSave();
    expect(KeyItem._records[0].keyinfo_ids).toEqual([2]);
});

test("editing a card and saving writes the value to the line", async () => {
    await mountItem();
    await contains(".o_one2many_form_card input").edit("新产品");
    await clickSave();
    expect(KeyInfo._records[0].product).toBe("新产品");
});

test("in readonly mode the cards are shown without add or delete buttons", async () => {
    await mountItem(`
        <form>
            <field name="name"/>
            <field name="keyinfo_ids" widget="one2many_form" readonly="1">
                <list editable="bottom">
                    <field name="product"/>
                    <field name="feedback"/>
                </list>
            </field>
        </form>
    `);
    expect(queryAll(".o_one2many_form_card").length).toBe(2);
    expect(queryAll(".o_one2many_form_add").length).toBe(0);
    expect(queryAll(".o_one2many_form_card .btn-close").length).toBe(0);
});

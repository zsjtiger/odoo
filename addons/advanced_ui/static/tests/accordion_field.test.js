import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Line extends models.Model {
    name = fields.Char();
    qty = fields.Integer();

    _records = [
        { id: 1, name: "Line A", qty: 2 },
        { id: 2, name: "Line B", qty: 5 },
    ];
}

class Order extends models.Model {
    name = fields.Char();
    line_ids = fields.One2many({ relation: "line" });

    _records = [{ id: 1, name: "Order 1", line_ids: [1, 2] }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="line_ids" widget="accordion" options="{'summary': 'name'}">
                    <list>
                        <field name="name"/>
                        <field name="qty"/>
                    </list>
                </field>
            </form>`,
    };
}

defineModels([Line, Order]);

test("accordion widget: one row per line, summary from the summary option", async () => {
    await mountView({ type: "form", resModel: "order", resId: 1 });
    expect(".o_accordion_item").toHaveCount(2);
    expect(queryAllTexts(".o_accordion_summary .o_accordion_title")).toEqual([
        "Line A",
        "Line B",
    ]);
    expect(".o_accordion_details").toHaveCount(0);
});

test("accordion widget: opening a row shows the other fields of the inline list", async () => {
    await mountView({ type: "form", resModel: "order", resId: 1 });
    await click(".o_accordion_summary");
    await animationFrame();
    expect(".o_accordion_details").toHaveCount(1);
    expect(".o_accordion_details [name='qty']").toHaveText("2");
});

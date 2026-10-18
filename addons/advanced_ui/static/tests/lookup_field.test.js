import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts, waitFor } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Partner extends models.Model {
    name = fields.Char();
    city = fields.Char();

    _records = [
        { id: 1, name: "Acme", city: "San Francisco" },
        { id: 2, name: "Paddy's Pub", city: "Boston, MA" },
    ];
}

class Order extends models.Model {
    name = fields.Char();
    partner_id = fields.Many2one({ relation: "partner" });

    _records = [{ id: 1, name: "Order 1", partner_id: false }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="partner_id" widget="lookup" options="{'subtitle': 'city'}"/>
            </form>`,
    };
}

class PlainOrder extends models.Model {
    _name = "plain.order";
    partner_id = fields.Many2one({ relation: "partner" });

    _records = [{ id: 1, partner_id: false }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="partner_id"/>
            </form>`,
    };
}

defineModels([Partner, Order, PlainOrder]);

test("lookup widget: suggestions show a tile, the name and the subtitle field", async () => {
    await mountView({ type: "form", resModel: "order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".o_lookup_option");
    expect(".o_lookup_option").toHaveCount(1);
    expect(queryAllTexts(".o_lookup_title")).toEqual(["Acme"]);
    expect(queryAllTexts(".o_lookup_subtitle")).toEqual(["San Francisco"]);
    expect(".o_lookup_tile").toHaveCount(1);
    expect(".o_lookup_tile").toHaveText("A");
});

test("default many2one dropdown is unchanged", async () => {
    await mountView({ type: "form", resModel: "plain.order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".dropdown-item");
    expect(".o_lookup_option").toHaveCount(0);
});

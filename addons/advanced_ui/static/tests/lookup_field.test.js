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
    type = fields.Char();

    _records = [
        { id: 1, name: "Acme", city: "San Francisco", type: "Account" },
        { id: 2, name: "Paddy's Pub", city: "Boston, MA", type: "Account" },
        { id: 3, name: "Acme Construction", city: "Grand Marais, MN", type: "Opportunity" },
    ];
}

class Order extends models.Model {
    name = fields.Char();
    partner_id = fields.Many2one({ relation: "partner" });

    _records = [{ id: 1, name: "Order 1", partner_id: false }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="partner_id" widget="lookup" options="{'subtitle': 'city', 'group': 'type'}"/>
            </form>`,
    };
}

class ScopedOrder extends models.Model {
    _name = "scoped.order";
    partner_id = fields.Many2one({ relation: "partner" });

    _records = [{ id: 1, partner_id: false }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="partner_id" widget="lookup" options="{'subtitle': 'city', 'group': 'type', 'scope': true}"/>
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

defineModels([Partner, Order, ScopedOrder, PlainOrder]);

test("lookup widget: suggestions show a tile, the name and the subtitle field", async () => {
    await mountView({ type: "form", resModel: "order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".o_lookup_option");
    expect(".o_lookup_option").toHaveCount(2);
    expect(queryAllTexts(".o_lookup_title")).toEqual(["Acme", "Acme Construction"]);
    expect(queryAllTexts(".o_lookup_subtitle")).toEqual(["San Francisco", "Grand Marais, MN"]);
    expect(".o_lookup_tile").toHaveCount(2);
    expect(".o_lookup_tile:eq(0)").toHaveText("A");
});

test("lookup widget: suggestions are split under a header per group value", async () => {
    await mountView({ type: "form", resModel: "order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".o_lookup_group_title");
    expect(queryAllTexts(".o_lookup_group_title")).toEqual(["Account", "Opportunity"]);
    expect(queryAllTexts(".o_lookup_title")).toEqual(["Acme", "Acme Construction"]);
    expect(".o_lookup_option").toHaveCount(2);
});

test("lookup widget: the scope selector keeps only the chosen group", async () => {
    await mountView({ type: "form", resModel: "scoped.order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".o_lookup_option");
    expect(".o_lookup_scope_button").toHaveText("All");
    await contains(".o_lookup_scope_button").click();
    await contains(".o_lookup_scope_menu .dropdown-item:contains(Opportunity)").click();
    await waitFor(".o_lookup_option");
    expect(".o_lookup_scope_button").toHaveText("Opportunity");
    expect(queryAllTexts(".o_lookup_title")).toEqual(["Acme Construction"]);
});

test("default many2one dropdown is unchanged", async () => {
    await mountView({ type: "form", resModel: "plain.order", resId: 1 });
    await contains("[name='partner_id'] input").edit("Acme", { confirm: false });
    await waitFor(".dropdown-item");
    expect(".o_lookup_option").toHaveCount(0);
});

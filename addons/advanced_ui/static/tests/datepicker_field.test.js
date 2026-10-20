import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    fieldInput,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Event extends models.Model {
    name = fields.Char();
    date = fields.Date();

    _records = [{ id: 1, name: "Kick-off", date: "2024-01-31" }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="name"/>
                <field name="date" widget="datepicker" options="{'format': 'dd/MM/yyyy'}"/>
            </form>`,
        list: /* xml */ `
            <list>
                <field name="name"/>
                <field name="date" widget="datepicker" options="{'format': 'dd/MM/yyyy'}"/>
            </list>`,
    };
}

class DefaultFormat extends models.Model {
    date = fields.Date();

    _records = [{ id: 1, date: "2024-01-31" }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="date" widget="datepicker"/>
            </form>`,
    };
}

defineModels({ ...webModels, Event, DefaultFormat });

test("form: the date is shown in the configured format", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    expect(".o_datepicker_input").toHaveValue("31/01/2024");
});

test("form: without format option, the language date format is used", async () => {
    await mountView({ type: "form", resModel: "default_format", resId: 1 });
    expect(".o_datepicker_input").toHaveValue("01/31/2024");
});

test("form: a date typed in the configured format is saved", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(args[1].date);
    });
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await fieldInput("date").edit("15/03/2024");
    expect(".o_datepicker_input").toHaveValue("15/03/2024");
    await contains(".o_form_button_save").click();
    expect.verifySteps(["2024-03-15"]);
});

test("form: an invalid text is reverted", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    await fieldInput("date").edit("not a date");
    expect(".o_datepicker_input").toHaveValue("31/01/2024");
});

test("form: the calendar icon opens the date picker", async () => {
    await mountView({ type: "form", resModel: "event", resId: 1 });
    expect(".o_date_picker").toHaveCount(0);
    await click(".o_datepicker_toggle");
    await animationFrame();
    expect(".o_date_picker").toHaveCount(1);
});

test("list: the date is shown in the configured format", async () => {
    await mountView({ type: "list", resModel: "event" });
    expect(queryAllTexts(".o_data_row .o_data_cell[name='date']")).toEqual(["31/01/2024"]);
});

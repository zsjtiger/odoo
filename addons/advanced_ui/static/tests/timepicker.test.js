import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, keyDown, queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fieldInput,
    fields,
    models,
    mountView,
    mountWithCleanup,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { TimePicker, filterTimes, parseTime, timesOfDay } from "@advanced_ui/timepicker/timepicker";

describe.current.tags("desktop");

/** Types the text in an input, with the input event that typing dispatches. */
function typeText(selector, text) {
    const input = document.querySelector(selector);
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
}

class Shift extends models.Model {
    name = fields.Char();
    start = fields.Char();
    hours = fields.Float();

    _records = [{ id: 1, name: "Morning", start: "09:30", hours: 9.5 }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="name"/>
                <field name="start" widget="timepicker"/>
                <field name="hours" widget="timepicker" options="{'step': 15}"/>
            </form>`,
    };
}

defineModels({ ...webModels, Shift });

test("the times of the day follow the step", () => {
    expect(timesOfDay(30)).toHaveLength(48);
    expect(timesOfDay(15)).toHaveLength(96);
    expect(timesOfDay(30).slice(0, 3)).toEqual(["00:00", "00:30", "01:00"]);
});

test("a typed time is parsed: hours, minutes, 0930 or 9.5", () => {
    expect(parseTime("9:30")).toBe("09:30");
    expect(parseTime("0930")).toBe("09:30");
    expect(parseTime("9")).toBe("09:00");
    expect(parseTime("9.5")).toBe("09:30");
    expect(parseTime("25:00")).toBe(false);
    expect(parseTime("10:99")).toBe(false);
    expect(parseTime("not a time")).toBe(false);
});

test("the list is filtered by the typed text", () => {
    expect(filterTimes(timesOfDay(30), "14")).toEqual(["14:00", "14:30"]);
    expect(filterTimes(timesOfDay(30), "")).toHaveLength(48);
});

test("the list shows the times, and picking one sets it", async () => {
    await mountWithCleanup(TimePicker, {
        props: { value: "", step: 30, onChange: (time) => expect.step(time) },
    });
    await click(".o_timepicker_input");
    await animationFrame();
    expect(queryAllTexts(".o_timepicker_option")).toHaveLength(48);
    // An input event, as typing does: edit would commit the text on blur
    typeText(".o_timepicker_input", "14");
    await animationFrame();
    expect(queryAllTexts(".o_timepicker_option")).toEqual(["14:00", "14:30"]);
    await click(".o_timepicker_option:nth-child(2)");
    await animationFrame();
    expect.verifySteps(["14:30"]);
});

test("Enter sets the typed time, and an invalid one is not set", async () => {
    await mountWithCleanup(TimePicker, {
        props: { value: "", step: 30, onChange: (time) => expect.step(time) },
    });
    await contains(".o_timepicker_input").edit("9.5");
    await keyDown("Enter");
    await animationFrame();
    await contains(".o_timepicker_input").edit("25:99");
    await keyDown("Enter");
    await animationFrame();
    expect.verifySteps(["09:30"]);
});

test("form: a char time is shown and saved as HH:MM", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(args[1].start);
    });
    await mountView({ type: "form", resModel: "shift", resId: 1 });
    expect(".o_field_widget[name='start'] input").toHaveValue("09:30");
    await fieldInput("start").edit("10:15");
    await contains(".o_form_button_save").click();
    expect.verifySteps(["10:15"]);
});

test("form: a float time is shown and saved as hours", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(args[1].hours);
    });
    await mountView({ type: "form", resModel: "shift", resId: 1 });
    expect(".o_field_widget[name='hours'] input").toHaveValue("09:30");
    await fieldInput("hours").edit("10:15");
    await contains(".o_form_button_save").click();
    expect.verifySteps([10.25]);
});

import { expect, test } from "@odoo/hoot";
import { moveAppInOrder } from "@web_enterprise/webclient/home_menu/app_order";

test("moveAppInOrder: moves an app after the previous one", () => {
    expect(moveAppInOrder(["a", "b", "c", "d"], "d", "a")).toEqual(["a", "d", "b", "c"]);
});

test("moveAppInOrder: moves an app to the front without a previous app", () => {
    expect(moveAppInOrder(["a", "b", "c"], "c")).toEqual(["c", "a", "b"]);
});

test("moveAppInOrder: moving an app towards the end", () => {
    expect(moveAppInOrder(["a", "b", "c"], "a", "c")).toEqual(["b", "c", "a"]);
});

test("moveAppInOrder: does not mutate its input", () => {
    const order = ["a", "b"];
    moveAppInOrder(order, "b");
    expect(order).toEqual(["a", "b"]);
});

test("moveAppInOrder: an app not in the order is inserted, nothing is dropped", () => {
    expect(moveAppInOrder(["a", "b"], "z", "a")).toEqual(["a", "z", "b"]);
});

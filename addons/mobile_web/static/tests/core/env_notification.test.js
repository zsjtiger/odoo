import { describe, expect, test } from "@odoo/hoot";
import { envOf } from "@mobile_web/core/env";
import { notify } from "@mobile_web/core/notification";

describe.current.tags("mobile");

test("notify passes the message and options to the notification service", () => {
    const calls = [];
    const service = { add: (message, options) => calls.push([message, options]) };
    notify(service, "Saved", { type: "success" });
    expect(calls).toEqual([["Saved", { type: "success" }]]);
});

test("notify works without options", () => {
    const calls = [];
    notify({ add: (message, options) => calls.push([message, options]) }, "Hello");
    expect(calls).toEqual([["Hello", {}]]);
});

test("envOf returns the component's env", () => {
    const env = { bus: "bus" };
    expect(envOf({ env })).toBe(env);
});

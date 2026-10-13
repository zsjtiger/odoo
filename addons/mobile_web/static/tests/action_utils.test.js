import { describe, expect, test } from "@odoo/hoot";
import {
    buildRouteState,
    getActionViews,
    getStateAction,
    hasFormView,
} from "@mobile_web/webclient/actions/action_utils";

describe.current.tags("mobile");

test("getActionViews follows view_mode order and maps view ids by type", () => {
    // 服务端 views 的顺序按 sequence(list 在前), 而 view_mode 是 kanban,list,form
    const action = {
        view_mode: "kanban,list,form",
        views: [[11, "list"], [12, "kanban"], [13, "form"]],
    };
    expect(getActionViews(action)).toEqual([
        [12, "kanban"],
        [11, "list"],
        [13, "form"],
    ]);
});

test("getActionViews uses false for a view_mode entry without a view id", () => {
    expect(getActionViews({ view_mode: "list,form", views: [[7, "list"]] })).toEqual([
        [7, "list"],
        [false, "form"],
    ]);
});

test("getActionViews falls back to action.views without view_mode", () => {
    expect(getActionViews({ views: [[3, "form"]] })).toEqual([[3, "form"]]);
});

test("getActionViews defaults to list and form when nothing is given", () => {
    expect(getActionViews({})).toEqual([
        [false, "list"],
        [false, "form"],
    ]);
});

test("hasFormView detects a form view in the view_mode", () => {
    expect(hasFormView({ view_mode: "kanban,form" })).toBe(true);
    expect(hasFormView({ view_mode: "kanban,list" })).toBe(false);
});

test("getStateAction prefers the path over the id", () => {
    expect(getStateAction({ id: 5, path: "companies" })).toBe("companies");
    expect(getStateAction({ id: 5, path: false })).toBe(5);
});

test("buildRouteState without a resId has no resId in the state or the stack", () => {
    const state = buildRouteState({ id: 5, path: "companies" });
    expect(state).toEqual({
        action: "companies",
        _isMobile: true,
        actionStack: [{ action: "companies", _isMobile: true }],
    });
});

test("buildRouteState with a resId puts it in both the state and the stack", () => {
    const state = buildRouteState({ id: 5 }, 42);
    expect(state.resId).toBe(42);
    expect(state.actionStack[0].resId).toBe(42);
});

test("buildRouteState with the 'new' marker keeps it in the stack", () => {
    const state = buildRouteState({ id: 5 }, "new");
    expect(state.actionStack[0].resId).toBe("new");
});

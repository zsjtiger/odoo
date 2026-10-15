import { describe, expect, test } from "@odoo/hoot";
import { buildFilterDomain, filterableFields, orderString, sortableFields } from "@mobile_web/views/record_filters";

describe.current.tags("mobile");

const COLUMNS = [
    { name: "name", field: { type: "char", string: "Name" } },
    { name: "image", field: { type: "binary", string: "Image" } },
    { name: "lines", field: { type: "one2many", string: "Lines" } },
    { name: "active", field: { type: "boolean", string: "Active" } },
    { name: "state", field: { type: "selection", string: "State", selection: [["a", "A"]] } },
    { name: "amount", field: { type: "float", string: "Amount" } },
    { name: "missing", field: undefined },
];

test("sortable fields are the scalar and relational columns, not binary or one2many", () => {
    expect(sortableFields(COLUMNS).map((f) => f.name)).toEqual(["name", "active", "state", "amount"]);
});

test("filterable fields exclude dates and binary, which the bar does not filter yet", () => {
    expect(filterableFields(COLUMNS).map((f) => f.name)).toEqual(["name", "active", "state", "amount"]);
});

test("each field keeps its label, and selections keep their options", () => {
    const state = sortableFields(COLUMNS).find((f) => f.name === "state");
    expect(state.label).toBe("State");
    expect(state.selection).toEqual([["a", "A"]]);
});

test("a char filter is a case-insensitive contains", () => {
    expect(buildFilterDomain({ name: "name", type: "char", value: "Alp" })).toEqual([["name", "ilike", "Alp"]]);
});

test("a selection filter is an exact match", () => {
    expect(buildFilterDomain({ name: "state", type: "selection", value: "a" })).toEqual([["state", "=", "a"]]);
});

test("a boolean filter compares with a real boolean", () => {
    expect(buildFilterDomain({ name: "active", type: "boolean", value: "true" })).toEqual([["active", "=", true]]);
    expect(buildFilterDomain({ name: "active", type: "boolean", value: "false" })).toEqual([["active", "=", false]]);
});

test("numeric filters compare with numbers", () => {
    expect(buildFilterDomain({ name: "amount", type: "float", value: "2.5" })).toEqual([["amount", "=", 2.5]]);
    expect(buildFilterDomain({ name: "qty", type: "integer", value: "3" })).toEqual([["qty", "=", 3]]);
});

test("an empty or missing filter adds no condition", () => {
    expect(buildFilterDomain(null)).toEqual([]);
    expect(buildFilterDomain({ name: "name", type: "char", value: "" })).toEqual([]);
});

test("the order string is the field and direction, or empty without a sort", () => {
    expect(orderString({ name: "name", dir: "desc" })).toBe("name DESC");
    expect(orderString(null)).toBe("");
});

test("with no sortable marks in the arch, every sortable column can be sorted", () => {
    const columns = [
        { name: "name", attrs: { name: "name" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount" }, field: { type: "float", string: "Amount" } },
    ];
    expect(sortableFields(columns).map((f) => f.name)).toEqual(["name", "amount"]);
});

test("marked columns are the only sortable ones once the arch marks any column", () => {
    const columns = [
        { name: "name", attrs: { name: "name", sortable: "1" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount" }, field: { type: "float", string: "Amount" } },
        { name: "active", attrs: { name: "active", sortable: "True" }, field: { type: "boolean", string: "Active" } },
    ];
    expect(sortableFields(columns).map((f) => f.name)).toEqual(["name", "active"]);
});

test("sortable=\"0\" excludes a column even when no other column is marked", () => {
    const columns = [
        { name: "name", attrs: { name: "name" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount", sortable: "0" }, field: { type: "float", string: "Amount" } },
    ];
    expect(sortableFields(columns).map((f) => f.name)).toEqual(["name"]);
});

test("a marked column of a type that cannot be sorted stays excluded", () => {
    const columns = [
        { name: "lines", attrs: { name: "lines", sortable: "1" }, field: { type: "one2many", string: "Lines" } },
        { name: "name", attrs: { name: "name" }, field: { type: "char", string: "Name" } },
    ];
    expect(sortableFields(columns).map((f) => f.name)).toEqual([]);
});

import { describe, expect, test } from "@odoo/hoot";
import { filterableFields, orderString, sortableFields } from "@mobile_web/views/record_filters";

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

test("with filterable marks in the arch, only the marked columns can be filtered", () => {
    const columns = [
        { name: "name", attrs: { name: "name", filterable: "1" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount" }, field: { type: "float", string: "Amount" } },
    ];
    expect(filterableFields(columns).map((f) => f.name)).toEqual(["name"]);
});

test("the sortable marks do not restrict the filterable fields", () => {
    const columns = [
        { name: "name", attrs: { name: "name", sortable: "1" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount" }, field: { type: "float", string: "Amount" } },
    ];
    expect(filterableFields(columns).map((f) => f.name)).toEqual(["name", "amount"]);
});

test("class marks mobile_sortable and mobile_filterable work where attributes are not allowed", () => {
    const columns = [
        { name: "name", attrs: { name: "name", class: "mobile_title mobile_sortable" }, field: { type: "char", string: "Name" } },
        { name: "amount", attrs: { name: "amount", class: "mobile_filterable" }, field: { type: "float", string: "Amount" } },
        { name: "active", attrs: { name: "active" }, field: { type: "boolean", string: "Active" } },
    ];
    expect(sortableFields(columns).map((f) => f.name)).toEqual(["name"]);
    expect(filterableFields(columns).map((f) => f.name)).toEqual(["amount"]);
});

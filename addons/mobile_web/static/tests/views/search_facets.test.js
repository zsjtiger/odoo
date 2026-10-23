import { describe, expect, test } from "@odoo/hoot";
import { facetFromRow, facetLeaf, facetsDomain, suggestionRows } from "@mobile_web/views/search_facets";

describe.current.tags("mobile");

const FIELDS = [
    { name: "name", label: "Name", type: "char" },
    { name: "partner_id", label: "Partner", type: "many2one" },
    { name: "amount", label: "Amount", type: "float" },
    { name: "state", label: "State", type: "selection", selection: [["draft", "Draft"], ["done", "Done"]] },
];

test("text facets search with ilike, many2one ids with =", () => {
    expect(facetLeaf({ name: "name", type: "char", value: "Alp" })).toEqual(["name", "ilike", "Alp"]);
    expect(facetLeaf({ name: "partner_id", type: "many2one", value: 7, display: "Acme" })).toEqual(["partner_id", "=", 7]);
    expect(facetLeaf({ name: "partner_id", type: "many2one", value: "ac", operator: "ilike" })).toEqual(["partner_id", "ilike", "ac"]);
});

test("selection and number facets match exactly", () => {
    expect(facetLeaf({ name: "state", type: "selection", value: "done" })).toEqual(["state", "=", "done"]);
    expect(facetLeaf({ name: "amount", type: "float", value: 3.5 })).toEqual(["amount", "=", 3.5]);
});

test("facets on different fields are combined with AND", () => {
    const domain = facetsDomain([
        { name: "name", type: "char", value: "Alp" },
        { name: "state", type: "selection", value: "done" },
    ]);
    expect(domain).toEqual([["name", "ilike", "Alp"], ["state", "=", "done"]]);
});

test("facets on the same field are combined with OR", () => {
    const domain = facetsDomain([
        { name: "state", type: "selection", value: "draft" },
        { name: "state", type: "selection", value: "done" },
    ]);
    expect(domain).toEqual(["|", ["state", "=", "draft"], ["state", "=", "done"]]);
});

test("three facets on one field need two OR operators before them", () => {
    const domain = facetsDomain([
        { name: "name", type: "char", value: "a" },
        { name: "name", type: "char", value: "b" },
        { name: "name", type: "char", value: "c" },
        { name: "amount", type: "float", value: 1 },
    ]);
    expect(domain).toEqual(["|", "|", ["name", "ilike", "a"], ["name", "ilike", "b"], ["name", "ilike", "c"], ["amount", "=", 1]]);
});

test("no text means no suggestions", () => {
    expect(suggestionRows("   ", FIELDS)).toEqual([]);
});

test("text suggests every text field, a record search for many2one and a number only when numeric", () => {
    const rows = suggestionRows("12", FIELDS);
    expect(rows.map((r) => [r.name, r.expandable])).toEqual([
        ["name", false],
        ["partner_id", true],
        ["amount", false],
    ]);
});

test("a selection field suggests the options whose label matches the text", () => {
    const rows = suggestionRows("dr", FIELDS);
    expect(rows.map((r) => r.name)).toEqual(["name", "partner_id", "state"]);
    const state = rows.find((r) => r.name === "state");
    expect(state.expandable).toBe(true);
    expect(state.expanded).toBe(false);
});

test("expanding a field lists its loaded options", () => {
    const rows = suggestionRows("ac", FIELDS, { partner_id: [[7, "Acme"]] }, "partner_id");
    const partner = rows.find((r) => r.name === "partner_id");
    expect(partner.expanded).toBe(true);
    expect(partner.options).toEqual([[7, "Acme"]]);
});

test("a text row becomes a facet with the text, a record row with its id", () => {
    const [nameRow] = suggestionRows("Alp", FIELDS);
    expect(facetFromRow(nameRow, null, 1)).toEqual({
        id: 1,
        name: "name",
        label: "Name",
        type: "char",
        value: "Alp",
        display: "Alp",
    });
    const partner = suggestionRows("ac", FIELDS).find((r) => r.name === "partner_id");
    expect(facetFromRow(partner, { value: 7, display: "Acme" }, 2)).toEqual({
        id: 2,
        name: "partner_id",
        label: "Partner",
        type: "many2one",
        value: 7,
        display: "Acme",
    });
    expect(facetFromRow(partner, null, 3)).toEqual({
        id: 3,
        name: "partner_id",
        label: "Partner",
        type: "many2one",
        value: "ac",
        display: "ac",
        operator: "ilike",
    });
});

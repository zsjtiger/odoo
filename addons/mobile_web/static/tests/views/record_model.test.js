import { describe, expect, test } from "@odoo/hoot";
import {
    buildSpec,
    normalizeFromServer,
    serializeForServer,
} from "@mobile_web/views/record_model";

describe.current.tags("mobile");

const FIELDS = {
    name: { type: "char" },
    partner_id: { type: "many2one", relation: "res.partner" },
    tag_ids: { type: "many2many", relation: "res.tag" },
    line_ids: { type: "one2many", relation: "res.line" },
    display_name: { type: "char" },
};

test("buildSpec reads scalars plainly and relations with their display_name", () => {
    const spec = buildSpec(FIELDS, ["name", "partner_id", "tag_ids", "line_ids"]);
    expect(spec.name).toEqual({});
    expect(spec.partner_id).toEqual({ fields: { display_name: {} } });
    expect(spec.tag_ids).toEqual({ fields: { display_name: {} } });
    expect(spec.line_ids).toEqual({ fields: { display_name: {} } });
});

test("buildSpec always asks for display_name and skips unknown fields", () => {
    const spec = buildSpec({ name: { type: "char" } }, ["name", "missing"]);
    expect(spec.display_name).toEqual({});
    expect(spec.missing).toBe(undefined);
});

test("normalizeFromServer turns many2one values into [id, name] or false", () => {
    const field = FIELDS.partner_id;
    expect(normalizeFromServer(field, false)).toBe(false);
    expect(normalizeFromServer(field, 7)).toEqual([7, null]);
    expect(normalizeFromServer(field, [7, "Ann"])).toEqual([7, "Ann"]);
    expect(normalizeFromServer(field, { id: 7, display_name: "Ann" })).toEqual([7, "Ann"]);
});

test("normalizeFromServer turns x2many values into a list of pairs", () => {
    const field = FIELDS.tag_ids;
    expect(normalizeFromServer(field, [{ id: 1, display_name: "A" }, 2])).toEqual([
        [1, "A"],
        [2, null],
    ]);
    expect(normalizeFromServer(field, undefined)).toEqual([]);
});

test("normalizeFromServer passes scalar values through", () => {
    expect(normalizeFromServer({ type: "char" }, "abc")).toBe("abc");
    expect(normalizeFromServer({ type: "integer" }, 0)).toBe(0);
});

test("serializeForServer writes many2one as its id", () => {
    expect(serializeForServer(FIELDS.partner_id, [7, "Ann"])).toBe(7);
    expect(serializeForServer(FIELDS.partner_id, false)).toBe(false);
});

test("serializeForServer writes many2many as a replace command", () => {
    expect(serializeForServer(FIELDS.tag_ids, [[1, "A"], [2, "B"]])).toEqual([[6, 0, [1, 2]]]);
    expect(serializeForServer(FIELDS.tag_ids, [])).toEqual([[6, 0, []]]);
});

test("serializeForServer does not write one2many (read-only in mobile)", () => {
    expect(serializeForServer(FIELDS.line_ids, [[1, "x"]])).toBe(undefined);
});

test("serializeForServer maps undefined scalars to false and keeps other values", () => {
    expect(serializeForServer({ type: "char" }, undefined)).toBe(false);
    expect(serializeForServer({ type: "char" }, "x")).toBe("x");
    expect(serializeForServer({ type: "boolean" }, true)).toBe(true);
});

test("a binary value read from the server is not written back unless it changed", () => {
    const field = { type: "binary" };
    expect(serializeForServer(field, { size: 926, checksum: "abc" })).toBe(undefined);
    expect(serializeForServer(field, "iVBORw0KGgo=")).toBe("iVBORw0KGgo=");
    expect(serializeForServer(field, false)).toBe(false);
});

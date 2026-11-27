import { describe, expect, test } from "@odoo/hoot";
import { MobileRecord, toUIData } from "@mobile_web/views/record";

describe.current.tags("mobile");

const FIELDS = {
    name: { type: "char" },
    partner_id: { type: "many2one", relation: "res.partner" },
    total: { type: "float", readonly: true },
    line_ids: { type: "one2many", relation: "res.line" },
};

test("a record without id is new and not dirty", () => {
    const record = new MobileRecord(FIELDS, false, { name: false });
    expect(record.isNew).toBe(true);
    expect(record.isDirty).toBe(false);
});

test("update changes the UI value and records the server value as a change", () => {
    const record = new MobileRecord(FIELDS, 4, { name: "old" });
    record.update("name", "new");
    expect(record.data.name).toBe("new");
    expect(record.changes).toEqual({ name: "new" });
    expect(record.isDirty).toBe(true);
});

test("update of a many2one stores the id as the change", () => {
    const record = new MobileRecord(FIELDS, 4, { partner_id: false });
    record.update("partner_id", [9, "Ann"]);
    expect(record.data.partner_id).toEqual([9, "Ann"]);
    expect(record.changes.partner_id).toBe(9);
});

test("setQuiet changes the value without marking the record dirty", () => {
    const record = new MobileRecord(FIELDS, 4, { name: "a" });
    record.setQuiet("name", "b");
    expect(record.data.name).toBe("b");
    expect(record.isDirty).toBe(false);
});

test("readonly fields are never written to the server", () => {
    const record = new MobileRecord(FIELDS, 4, { total: 1 });
    record.update("total", 5);
    expect(record.data.total).toBe(5);
    expect(record.isDirty).toBe(false);
});

test("one2many values are not written", () => {
    const record = new MobileRecord(FIELDS, 4, { line_ids: [] });
    record.update("line_ids", [[1, "x"]]);
    expect(record.isDirty).toBe(false);
});

test("markDefaults records the current values of the given fields", () => {
    const record = new MobileRecord(FIELDS, false, { name: "Default", partner_id: [3, "X"] });
    record.markDefaults(["name", "partner_id", "total"]);
    expect(record.changes).toEqual({ name: "Default", partner_id: 3 });
});

test("reset gives the record its saved id and data and clears the changes", () => {
    const record = new MobileRecord(FIELDS, false, { name: "x" });
    record.update("name", "y");
    record.reset(12, { name: "y" });
    expect(record.resId).toBe(12);
    expect(record.isNew).toBe(false);
    expect(record.isDirty).toBe(false);
    expect(record.data.name).toBe("y");
});

test("toUIData maps server values, skips unknown fields and keeps display_name", () => {
    const raw = { id: 1, name: "A", partner_id: { id: 5, display_name: "P" }, extra: "ignored", display_name: "A" };
    const data = toUIData(FIELDS, raw, ["name", "partner_id", "missing"]);
    expect(data.name).toBe("A");
    expect(data.partner_id).toEqual([5, "P"]);
    expect(data.extra).toBe(undefined);
    expect(data.missing).toBe(undefined);
    expect(data.display_name).toBe("A");
});

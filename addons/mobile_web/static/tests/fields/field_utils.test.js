import { describe, expect, test } from "@odoo/hoot";
import { displayOrEmpty, hasDisplayValue } from "@mobile_web/fields/field_utils";
import { hasMoreRecords } from "@mobile_web/views/infinite_scroll";

describe.current.tags("mobile");

test("hasDisplayValue hides empty values and keeps real ones", () => {
    expect(hasDisplayValue(false)).toBe(false);
    expect(hasDisplayValue(null)).toBe(false);
    expect(hasDisplayValue(undefined)).toBe(false);
    expect(hasDisplayValue("")).toBe(false);
    expect(hasDisplayValue([])).toBe(false);
    expect(hasDisplayValue(0)).toBe(true);
    expect(hasDisplayValue("x")).toBe(true);
    expect(hasDisplayValue([[1, "A"]])).toBe(true);
});

test("displayOrEmpty shows nothing for false, null and undefined", () => {
    expect(displayOrEmpty(false)).toBe("");
    expect(displayOrEmpty(null)).toBe("");
    expect(displayOrEmpty(undefined)).toBe("");
    expect(displayOrEmpty(0)).toBe("0");
    expect(displayOrEmpty("abc")).toBe("abc");
});

test("hasMoreRecords is true only while some records are not loaded", () => {
    expect(hasMoreRecords({ state: { records: [], total: null } })).toBe(false);
    expect(hasMoreRecords({ state: { records: [1], total: 3 } })).toBe(true);
    expect(hasMoreRecords({ state: { records: [1, 2, 3], total: 3 } })).toBe(false);
});

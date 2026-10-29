import { describe, expect, test } from "@odoo/hoot";
import { mobileFilterDomain } from "@mobile_web/views/mobile_filters";

describe.current.tags("mobile");

const MINE = { key: "mine", domain: [["user_id", "=", 2]] };
const SPEAKER = { key: "speaker", domain: [["is_urgent", "=", true]] };
const NOT_SPEAKER = { key: "not_speaker", domain: [["is_urgent", "=", false]] };

test("nothing selected gives no restriction", () => {
    const sections = [{ name: "a", options: [MINE] }];
    expect(mobileFilterDomain(sections, { options: [], cards: {} })).toEqual([]);
});

test("a selected option adds its domain", () => {
    const sections = [{ name: "a", options: [MINE] }];
    expect(mobileFilterDomain(sections, { options: ["mine"], cards: {} })).toEqual([["user_id", "=", 2]]);
});

test("options of one section are OR-ed", () => {
    const sections = [{ name: "speaker", options: [SPEAKER, NOT_SPEAKER] }];
    expect(mobileFilterDomain(sections, { options: ["speaker", "not_speaker"], cards: {} })).toEqual([
        "|",
        ["is_urgent", "=", true],
        ["is_urgent", "=", false],
    ]);
});

test("sections are AND-ed", () => {
    const sections = [
        { name: "a", options: [MINE] },
        { name: "speaker", options: [SPEAKER] },
    ];
    expect(mobileFilterDomain(sections, { options: ["mine", "speaker"], cards: {} })).toEqual([
        ["user_id", "=", 2],
        ["is_urgent", "=", true],
    ]);
});

test("selected cards add an in condition on the many2one field", () => {
    const sections = [{ name: "rep", options: [], cards: { field: "user_id" } }];
    expect(mobileFilterDomain(sections, { options: [], cards: { user_id: [3, 5] } })).toEqual([["user_id", "in", [3, 5]]]);
});

test("a card and an option of the same section are OR-ed", () => {
    const sections = [{ name: "rep", options: [MINE], cards: { field: "user_id" } }];
    expect(mobileFilterDomain(sections, { options: ["mine"], cards: { user_id: [3] } })).toEqual([
        "|",
        ["user_id", "=", 2],
        ["user_id", "in", [3]],
    ]);
});

test("a multi-condition option is grouped with AND", () => {
    const section = { name: "a", options: [{ key: "x", domain: [["a", "=", 1], ["b", "=", 2]] }] };
    expect(mobileFilterDomain([section], { options: ["x"], cards: {} })).toEqual(["&", ["a", "=", 1], ["b", "=", 2]]);
});

test("an option with an empty domain does not restrict its section", () => {
    const sections = [
        { name: "a", options: [{ key: "all", domain: [] }, SPEAKER] },
    ];
    expect(mobileFilterDomain(sections, { options: ["all", "speaker"], cards: {} })).toEqual([]);
});

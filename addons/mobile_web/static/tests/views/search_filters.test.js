import { describe, expect, test } from "@odoo/hoot";
import { parseSearchFilters } from "@mobile_web/views/search_filters";

describe.current.tags("mobile");

test("only filters with a domain are kept, group-by options are ignored", () => {
    const arch = `<search>
        <filter name="urgent" string="Urgent" domain="[('is_urgent', '=', True)]"/>
        <group>
            <filter name="group_state" string="Status" context="{'group_by': 'state'}"/>
        </group>
        <filter name="done" string="Done" domain="[('state', '=', 'done')]"/>
    </search>`;
    expect(parseSearchFilters(arch)).toEqual([
        { key: "urgent", label: "Urgent", domain: "[('is_urgent', '=', True)]" },
        { key: "done", label: "Done", domain: "[('state', '=', 'done')]" },
    ]);
});

test("a filter without a name gets a generated key and its name as label", () => {
    const filters = parseSearchFilters(`<search><filter domain="[('id', '>', 0)]"/></search>`);
    expect(filters.length).toBe(1);
    expect(filters[0].key).toBe("filter_0");
    expect(filters[0].label).toBe("filter_0");
});

test("no arch means no filters", () => {
    expect(parseSearchFilters(undefined)).toEqual([]);
});

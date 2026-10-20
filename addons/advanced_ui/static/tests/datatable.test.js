import { describe, expect, test } from "@odoo/hoot";
import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { animationFrame, click, keyDown, queryAll, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { DataTable } from "@advanced_ui/datatable/datatable";
import { Pager } from "@web/core/components/pager/pager";
import { buildFilterDomain, matchesDomain } from "@advanced_ui/datatable/filter_domain";
import { registry } from "@web/core/framework/registry";
import { listView } from "@web/views/list/list_view";
import { defineModels, fields, models, mountView, webModels } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Foo extends models.Model {
    foo = fields.Char();
    _records = [
        { id: 1, foo: "yop" },
        { id: 2, foo: "blip" },
        { id: 3, foo: "gnap" },
        { id: 4, foo: "abc" },
    ];
}
const { ResCompany, ResPartner, ResUsers } = webModels;
defineModels([Foo, ResCompany, ResPartner, ResUsers]);

/** Renders the records of a list with DataTable, using a field column. */
class DataTableListRenderer extends Component {
    static template = xml`<DataTable columns="this.columns" rows="this.props.list.records"/>`;
    static components = { DataTable };
    props = useProps({ list: t.any(), archInfo: t.any().optional() });

    setup() {
        this.columns = [{ key: "foo", label: "Foo", type: "field" }];
    }
}
registry.category("views").add("datatable_list_test", { ...listView, Renderer: DataTableListRenderer });

const columns = [
    { key: "name", label: "Name", sortable: true },
    { key: "amount", label: "Amount", type: "number", sortable: true },
];

const rows = [
    { id: 1, name: "Acme", amount: 300 },
    { id: 2, name: "Globex", amount: 100 },
    { id: 3, name: "Initech", amount: 200 },
];

/**
 * @param {Object} [props]
 */
function mountTable(props = {}) {
    return mountWithCleanup(DataTable, { props: { columns, rows, ...props } });
}

test("datatable: renders a header and one row per record", async () => {
    await mountTable();
    expect(".o_datatable thead th").toHaveCount(2);
    expect("tbody tr").toHaveCount(3);
});

test("datatable: headless hides the header", async () => {
    await mountTable({ headless: true });
    expect(".o_datatable_headless").toHaveCount(1);
    expect("thead").toHaveCount(0);
    expect("tbody tr").toHaveCount(3);
});

test("datatable: layout classes follow the props", async () => {
    await mountTable({ striped: true, bordered: true, noRowHover: true });
    expect(".o_datatable_striped").toHaveCount(1);
    expect(".o_datatable_bordered").toHaveCount(1);
    expect(".o_datatable_no_hover").toHaveCount(1);
});

test("datatable: clicking a sortable header sorts ascending then descending", async () => {
    await mountTable();
    await click(queryAll("thead th")[1]);
    await animationFrame();
    expect(queryAllTexts("tbody tr td:nth-child(2)")).toEqual(["100", "200", "300"]);
    await click(queryAll("thead th")[1]);
    await animationFrame();
    expect(queryAllTexts("tbody tr td:nth-child(2)")).toEqual(["300", "200", "100"]);
});

test("datatable: a non sortable header does not sort", async () => {
    await mountTable({ columns: [{ key: "name", label: "Name" }, ...columns.slice(1)] });
    await click(queryAll("thead th")[0]);
    await animationFrame();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Acme", "Globex", "Initech"]);
});

test("datatable: multi selection toggles rows and the select all checkbox", async () => {
    const selections = [];
    await mountTable({ selection: "multi", onSelectionChange: (ids) => selections.push(ids) });
    await click("tbody input[type=checkbox]");
    await animationFrame();
    expect(".o_datatable_selected").toHaveCount(1);
    await click("thead input[type=checkbox]");
    await animationFrame();
    expect(".o_datatable_selected").toHaveCount(3);
    expect(selections.at(-1)).toEqual([1, 2, 3]);
});

test("datatable: single selection keeps one row selected", async () => {
    await mountTable({ selection: "single" });
    await click(queryAll("tbody input[type=radio]")[0]);
    await animationFrame();
    await click(queryAll("tbody input[type=radio]")[2]);
    await animationFrame();
    expect(".o_datatable_selected").toHaveCount(1);
    expect(queryAll("tbody tr")[2]).toHaveClass("o_datatable_selected");
});

test("datatable: arrow keys move the focus between cells", async () => {
    await mountTable({ keyboard: true });
    queryOne('[data-cell="0-0"]').focus();
    await keyDown("ArrowDown");
    await animationFrame();
    expect(document.activeElement).toBe(queryOne('[data-cell="1-0"]'));
    await keyDown("ArrowRight");
    await animationFrame();
    expect(document.activeElement).toBe(queryOne('[data-cell="1-1"]'));
});

test("datatable: row actions open a menu and run the action", async () => {
    const calls = [];
    await mountTable({
        rowActions: [{ label: "Edit", onSelect: (row) => calls.push(row.name) }],
    });
    await click(queryAll(".o_datatable_action_toggle")[1]);
    await animationFrame();
    expect(".o_datatable_menu").toHaveCount(1);
    await click(".o_datatable_menu .dropdown-item");
    await animationFrame();
    expect(calls).toEqual(["Globex"]);
    expect(".o_datatable_menu").toHaveCount(0);
});

test("datatable: scrolling to the bottom calls onLoadMore", async () => {
    let calls = 0;
    await mountTable({
        scrollable: true,
        maxHeight: "100px",
        rows: Array.from({ length: 50 }, (_, i) => ({ id: i, name: `Row ${i}`, amount: i })),
        onLoadMore: () => calls++,
    });
    const scrollArea = queryOne(".o_datatable");
    scrollArea.scrollTop = scrollArea.scrollHeight;
    scrollArea.dispatchEvent(new Event("scroll"));
    await animationFrame();
    // The browser may fire its own scroll event as well, so only require that it was called.
    expect(calls).toBeGreaterThan(0);
});

test("datatable: dragging a header edge resizes its column", async () => {
    await mountTable({ resizable: true });
    const resizer = queryAll(".o_datatable_resizer")[0];
    const width = queryAll("thead th")[0].offsetWidth;
    resizer.dispatchEvent(new PointerEvent("pointerdown", { clientX: 100, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointermove", { clientX: 100 + 80 }));
    window.dispatchEvent(new PointerEvent("pointerup", { clientX: 180 }));
    await animationFrame();
    expect(queryAll("thead th")[0].offsetWidth).toBeGreaterThan(width);
});

test("datatable: the cell slot renders custom content in every cell", async () => {
    class Wrapper extends Component {
        static template = xml`
            <DataTable columns="this.columns" rows="this.rows">
                <t t-set-slot="cell" t-slot-scope="scope">
                    <b class="custom-cell" t-out="scope.text"/>
                </t>
            </DataTable>`;
        static components = { DataTable };

        setup() {
            this.columns = columns;
            this.rows = rows;
        }
    }
    await mountWithCleanup(Wrapper);
    expect(".custom-cell").toHaveCount(6);
    expect(queryAllTexts(".custom-cell")).toEqual(["Acme", "300", "Globex", "100", "Initech", "200"]);
});

test("datatable: the parent pages the rows with a Pager", async () => {
    const allRows = Array.from({ length: 10 }, (_, i) => ({ id: i, name: `Row ${i}`, amount: i }));
    class Paged extends Component {
        static template = xml`
            <Pager offset="this.state.offset" limit="this.state.limit" total="this.allRows.length"
                onUpdate="(params) => this.onUpdate(params)"/>
            <DataTable columns="this.columns" rows="this.currentPage"/>`;
        static components = { DataTable, Pager };

        setup() {
            this.columns = columns;
            this.allRows = allRows;
            this.state = proxy({ offset: 0, limit: 3 });
        }

        get currentPage() {
            return this.allRows.slice(this.state.offset, this.state.offset + this.state.limit);
        }

        onUpdate({ offset, limit }) {
            this.state.offset = offset;
            this.state.limit = limit;
        }
    }
    await mountWithCleanup(Paged);
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 0", "Row 1", "Row 2"]);
    await click(".o_pager_next");
    await animationFrame();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 3", "Row 4", "Row 5"]);
});

test("datatable: field columns render the Odoo field widget of each record", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list js_class="datatable_list_test"><field name="foo"/></list>`,
    });

    expect(".o_datatable .o_field_char").toHaveCount(4);
    expect(queryAllTexts(".o_datatable .o_field_char")).toEqual(["yop", "blip", "gnap", "abc"]);
});

/**
 * Sets the value of a filter control and fires the change event the control listens to.
 * @param {string|HTMLElement} target
 * @param {string} value
 */
function setFilterValue(target, value) {
    const input = typeof target === "string" ? queryOne(target) : target;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * Opens the filter popover of the column at the given index.
 * @param {number} index
 */
async function openFilter(index) {
    await click(queryAll(".o_datatable_filter_toggle")[index]);
    await animationFrame();
}

/** Applies the filter popover that is open. */
async function applyFilter() {
    await click(".o_datatable_filter_apply");
    await animationFrame();
}

test("datatable: header filters narrow the rows and paging follows them", async () => {
    const allRows = Array.from({ length: 10 }, (_, i) => ({ id: i, name: `Row ${i}`, amount: i }));
    const filterColumns = [
        { key: "name", label: "Name", filter: "text" },
        { key: "amount", label: "Amount", type: "number", filter: "number" },
    ];
    class Filtered extends Component {
        static template = xml`
            <DataTable columns="this.columns" rows="this.pageRows" filters="this.state.filters"
                onFilterChange="(key, value) => this.onFilterChange(key, value)"/>
            <Pager offset="this.state.offset" limit="this.state.limit" total="this.filteredRows.length"
                onUpdate="(params) => this.onUpdate(params)"/>`;
        static components = { DataTable, Pager };

        setup() {
            this.columns = filterColumns;
            this.state = proxy({ offset: 0, limit: 3, filters: {} });
        }

        get filteredRows() {
            const domain = buildFilterDomain(filterColumns, this.state.filters);
            return allRows.filter((row) => matchesDomain(row, domain));
        }

        get pageRows() {
            return this.filteredRows.slice(this.state.offset, this.state.offset + this.state.limit);
        }

        onFilterChange(key, value) {
            this.state.filters[key] = value;
            this.state.offset = 0;
        }

        onUpdate({ offset, limit }) {
            this.state.offset = offset;
            this.state.limit = limit;
        }
    }
    await mountWithCleanup(Filtered);
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 0", "Row 1", "Row 2"]);

    await openFilter(0);
    setFilterValue(".o_datatable_filter_popover input[aria-label=Value]", "Row 1");
    await applyFilter();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 1"]);

    await openFilter(0);
    setFilterValue(".o_datatable_filter_popover input[aria-label=Value]", "");
    await applyFilter();
    await openFilter(1);
    setFilterValue(".o_datatable_filter_popover input[aria-label=Minimum]", "3");
    await applyFilter();
    // Amounts 3 to 9 match: the first page shows three of them.
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 3", "Row 4", "Row 5"]);
    await click(".o_pager_next");
    await animationFrame();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["Row 6", "Row 7", "Row 8"]);
});

test("datatable: date filters produce a domain on the date strings", async () => {
    const columns = [{ key: "closeDate", label: "Close", type: "date", filter: "date" }];
    expect(buildFilterDomain(columns, { closeDate: { from: "2015-04-01", to: "2015-04-30" } })).toEqual([
        ["closeDate", ">=", "2015-04-01"],
        ["closeDate", "<=", "2015-04-30"],
    ]);
    expect(buildFilterDomain(columns, { closeDate: { from: "2015-04-01", to: "" } })).toEqual([
        ["closeDate", ">=", "2015-04-01"],
    ]);
});

test("datatable: datetime filters use the start and end of the days, in UTC", async () => {
    const columns = [{ key: "createdAt", label: "Created", type: "date", filter: "datetime" }];
    const [lower, upper] = buildFilterDomain(columns, {
        createdAt: { from: "2015-04-01", to: "2015-04-30" },
    }).map(([, , value]) => value);
    expect(lower).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(upper).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(lower < upper).toBe(true);
});

test("datatable: date range filters narrow the rows", async () => {
    const dateRows = [
        { id: 1, name: "A", closeDate: "2015-03-31" },
        { id: 2, name: "B", closeDate: "2015-04-10" },
        { id: 3, name: "C", closeDate: "2015-04-20" },
        { id: 4, name: "D", closeDate: "2015-05-02" },
    ];
    const dateColumns = [
        { key: "name", label: "Name" },
        { key: "closeDate", label: "Close", type: "date", filter: "date" },
    ];
    class DateFiltered extends Component {
        static template = xml`
            <DataTable columns="this.columns" rows="this.pageRows" filters="this.state.filters"
                onFilterChange="(key, value) => this.onFilterChange(key, value)"/>`;
        static components = { DataTable };

        setup() {
            this.columns = dateColumns;
            this.state = proxy({ filters: {} });
        }

        get pageRows() {
            const domain = buildFilterDomain(dateColumns, this.state.filters);
            return dateRows.filter((row) => matchesDomain(row, domain));
        }

        onFilterChange(key, value) {
            this.state.filters[key] = value;
        }
    }
    await mountWithCleanup(DateFiltered);
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["A", "B", "C", "D"]);

    await openFilter(0);
    setFilterValue(".o_datatable_filter_popover input[aria-label=From]", "2015-04-01");
    setFilterValue(".o_datatable_filter_popover input[aria-label=To]", "2015-04-30");
    await applyFilter();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["B", "C"]);
});

test("datatable: selection filter applies the checked options and Clear removes it", async () => {
    const stageRows = [
        { id: 1, name: "A", stage: "open" },
        { id: 2, name: "B", stage: "won" },
        { id: 3, name: "C", stage: "lost" },
        { id: 4, name: "D", stage: "won" },
    ];
    const stageColumns = [
        { key: "name", label: "Name" },
        {
            key: "stage",
            label: "Stage",
            filter: "selection",
            selection: [
                ["open", "Open"],
                ["won", "Won"],
                ["lost", "Lost"],
            ],
        },
    ];
    class StageFiltered extends Component {
        static template = xml`
            <DataTable columns="this.columns" rows="this.pageRows" filters="this.state.filters"
                onFilterChange="(key, value) => this.onFilterChange(key, value)"/>`;
        static components = { DataTable };

        setup() {
            this.columns = stageColumns;
            this.state = proxy({ filters: {} });
        }

        get pageRows() {
            const domain = buildFilterDomain(stageColumns, this.state.filters);
            return stageRows.filter((row) => matchesDomain(row, domain));
        }

        onFilterChange(key, value) {
            this.state.filters[key] = value;
        }
    }
    await mountWithCleanup(StageFiltered);
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["A", "B", "C", "D"]);

    await openFilter(0);
    // Checkboxes: all, open, won, lost. Check "Won".
    await click(queryAll(".o_datatable_filter_popover input[type=checkbox]")[2]);
    await applyFilter();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["B", "D"]);

    await openFilter(0);
    await click(".o_datatable_filter_clear");
    await animationFrame();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["A", "B", "C", "D"]);
});

test("datatable: relation filter picks records in a dialog and filters the rows", async () => {
    const partners = [
        { id: 1, name: "Alice" },
        { id: 2, name: "Bob" },
        { id: 3, name: "Carol" },
    ];
    const relationRows = [
        { id: 1, name: "A", partnerId: 1 },
        { id: 2, name: "B", partnerId: 2 },
        { id: 3, name: "C", partnerId: 3 },
        { id: 4, name: "D", partnerId: 1 },
    ];
    const relationColumns = [
        { key: "name", label: "Name" },
        {
            key: "partnerId",
            label: "Partner",
            filter: "relation",
            searchRecords: async (term) =>
                partners.filter((partner) => partner.name.toLowerCase().includes(term.toLowerCase())),
        },
    ];
    class RelationFiltered extends Component {
        static template = xml`
            <DataTable columns="this.columns" rows="this.pageRows" filters="this.state.filters"
                onFilterChange="(key, value) => this.onFilterChange(key, value)"/>`;
        static components = { DataTable };

        setup() {
            this.columns = relationColumns;
            this.state = proxy({ filters: {} });
        }

        get pageRows() {
            const domain = buildFilterDomain(relationColumns, this.state.filters);
            return relationRows.filter((row) => matchesDomain(row, domain));
        }

        onFilterChange(key, value) {
            this.state.filters[key] = value;
        }
    }
    await mountWithCleanup(RelationFiltered);
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["A", "B", "C", "D"]);

    await openFilter(0);
    await click(".o_datatable_relation_select");
    await animationFrame();
    setFilterValue(".o_relation_filter_search", "ali");
    await animationFrame();
    await animationFrame();
    expect(queryAllTexts(".modal label")).toEqual(["Alice"]);
    await click(".modal input[type=checkbox]");
    await animationFrame();
    await click(".o_relation_filter_confirm");
    await animationFrame();
    await applyFilter();
    expect(queryAllTexts("tbody tr td:first-child")).toEqual(["A", "D"]);
});

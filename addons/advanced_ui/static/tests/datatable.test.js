import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { animationFrame, click, keyDown, queryAll, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { DataTable } from "@advanced_ui/datatable/datatable";

describe.current.tags("desktop");

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

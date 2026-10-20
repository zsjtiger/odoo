import { Component, onWillUnmount, proxy, signal, t, useEffect, useProps } from "@odoo/owl";
import { uniqueId } from "@web/core/utils/functions";
import { Field } from "@web/views/fields/field";

/**
 * DataTable: a table with the layouts and behaviours of the list demo.
 *
 * Props:
 * - columns: [{ key, label, type, sortable, fixed, format }]
 *   - type: "text" (default), "number", "date" (ISO string), "link", "email" or "field"
 *     "field" renders the Odoo field widget of the record: rows must then be records
 *     of a model, and the column key is the field name. Such columns are not sortable.
 *   - sortable: a click on the header sorts the rows (default false)
 *   - fixed: the column cannot be resized (default false)
 *   - format(value, row): the text shown in the cell (default: the value)
 * - rows: [{ id, ...values }], each row needs a unique id
 * - filters: values of the header filters, keyed by column key (see filter_domain.js)
 * - onFilterChange(key, value): called when a header filter changes. The parent decides
 *   what the filter means (usually a domain), DataTable only shows the controls.
 *   A column opts in with `filter: "text" | "selection" | "bool" | "number"`.
 * - sortKey, sortDirection ("asc" | "desc"): the initial sort
 * - striped, bordered, headless, fixedLayout, noRowHover: layout booleans
 * - selection: "none" (default), "multi" (checkboxes) or "single" (radio buttons)
 * - resizable: the columns can be resized by dragging the edge of their header
 * - keyboard: arrow keys move between the cells (default true)
 * - scrollable, maxHeight: the rows scroll in an area with a sticky header
 * - rowActions: [{ label, onSelect(row) }], shows a menu on each row
 * - onLoadMore(): called when the bottom of a scrollable table is reached
 * - slot "cell": replaces the content of each cell. It receives { row, column, value, text },
 *   where text is the formatted value. Use it to render field components or badges.
 * - onSelectionChange(selectedIds)
 */
export class DataTable extends Component {
    static template = "advanced_ui.DataTable";
    static components = { Field };
    props = useProps({
        columns: t.array(),
        rows: t.array(),
        sortKey: t.string().optional(),
        sortDirection: t.string().optional(),
        striped: t.boolean().optional(),
        bordered: t.boolean().optional(),
        headless: t.boolean().optional(),
        fixedLayout: t.boolean().optional(),
        noRowHover: t.boolean().optional(),
        selection: t.string().optional(),
        resizable: t.boolean().optional(),
        keyboard: t.boolean().optional(),
        scrollable: t.boolean().optional(),
        maxHeight: t.string().optional(),
        rowActions: t.array().optional(),
        onLoadMore: t.function().optional(),
        onSelectionChange: t.function().optional(),
        slots: t.object().optional(),
        filters: t.object().optional(),
        onFilterChange: t.function().optional(),
    });

    setup() {
        this.state = proxy({
            sortKey: this.props.sortKey || null,
            sortDirection: this.props.sortDirection || "asc",
            selectedIds: [],
            widths: {},
            focus: { row: 0, col: 0 },
            menuRowId: null,
            loading: false,
        });
        this.radioName = uniqueId("o_datatable_radio_");
        this.rootRef = signal.ref();
        this.selectAllRef = signal.ref();
        this.resizeListeners = null;
        useEffect(() => {
            const checkbox = this.selectAllRef();
            if (checkbox) {
                checkbox.indeterminate = this.selectedCount > 0 && !this.allSelected;
            }
        });
        onWillUnmount(() => this.stopResize());
    }

    get sortedRows() {
        const rows = [...this.props.rows];
        const column = this.props.columns.find((col) => col.key === this.state.sortKey);
        if (!column) {
            return rows;
        }
        const direction = this.state.sortDirection === "asc" ? 1 : -1;
        const value = (row) =>
            column.type === "date" ? Date.parse(row[column.key]) : row[column.key];
        return rows.sort((a, b) => {
            const [valueA, valueB] = [value(a), value(b)];
            if (valueA < valueB) {
                return -direction;
            }
            return valueA > valueB ? direction : 0;
        });
    }

    get hasFilters() {
        return this.props.columns.some((column) => column.filter);
    }

    filterValue(column) {
        return this.props.filters?.[column.key] ?? "";
    }

    changeFilter(column, value) {
        this.props.onFilterChange?.(column.key, value);
    }

    changeNumberFilter(column, bound, value) {
        const current = this.props.filters?.[column.key] || {};
        this.props.onFilterChange?.(column.key, { ...current, [bound]: value });
    }

    get allSelected() {
        return this.props.rows.length > 0 && this.props.rows.every((row) => this.isSelected(row));
    }

    get selectedCount() {
        return this.state.selectedIds.length;
    }

    get colspan() {
        let count = this.props.columns.length;
        count += this.props.selection && this.props.selection !== "none" ? 1 : 0;
        return count + (this.props.rowActions ? 1 : 0);
    }

    isSelected(row) {
        return this.state.selectedIds.includes(row.id);
    }

    selectRow(row) {
        if (this.props.selection === "single") {
            this.state.selectedIds = [row.id];
        } else if (this.isSelected(row)) {
            this.state.selectedIds = this.state.selectedIds.filter((id) => id !== row.id);
        } else {
            this.state.selectedIds = [...this.state.selectedIds, row.id];
        }
        this.props.onSelectionChange?.(this.state.selectedIds);
    }

    toggleAll() {
        this.state.selectedIds = this.allSelected ? [] : this.props.rows.map((row) => row.id);
        this.props.onSelectionChange?.(this.state.selectedIds);
    }

    sortBy(column) {
        if (!column.sortable) {
            return;
        }
        if (this.state.sortKey === column.key) {
            this.state.sortDirection = this.state.sortDirection === "asc" ? "desc" : "asc";
        } else {
            this.state.sortKey = column.key;
            this.state.sortDirection = "asc";
        }
    }

    ariaSort(column) {
        if (this.state.sortKey !== column.key) {
            return "none";
        }
        return this.state.sortDirection === "asc" ? "ascending" : "descending";
    }

    sortIndicator(column) {
        if (this.state.sortKey !== column.key) {
            return "";
        }
        return this.state.sortDirection === "asc" ? "↑" : "↓";
    }

    cellText(column, row) {
        const value = row[column.key] ?? "";
        return column.format ? column.format(value, row) : value;
    }

    widthStyle(column) {
        const width = this.state.widths[column.key];
        return width ? `width: ${width}px;` : "";
    }

    startResize(ev, column) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = ev.target.closest("th").offsetWidth;
        const onMove = (moveEv) => {
            this.state.widths[column.key] = Math.max(60, startWidth + moveEv.clientX - startX);
        };
        const onUp = () => this.stopResize();
        this.stopResize();
        this.resizeListeners = { onMove, onUp };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    stopResize() {
        if (!this.resizeListeners) {
            return;
        }
        window.removeEventListener("pointermove", this.resizeListeners.onMove);
        window.removeEventListener("pointerup", this.resizeListeners.onUp);
        this.resizeListeners = null;
    }

    isFocused(rowIndex, colIndex) {
        return this.state.focus.row === rowIndex && this.state.focus.col === colIndex;
    }

    setFocus(rowIndex, colIndex) {
        this.state.focus = { row: rowIndex, col: colIndex };
    }

    getCellEl({ row, col }) {
        return this.rootRef()?.querySelector(`[data-cell="${row}-${col}"]`);
    }

    onKeydown(ev) {
        if (this.props.keyboard === false) {
            return;
        }
        const { row, col } = this.state.focus;
        const lastRow = this.sortedRows.length - 1;
        const lastCol = this.props.columns.length - 1;
        const moves = {
            ArrowDown: { row: Math.min(row + 1, lastRow), col },
            ArrowUp: { row: Math.max(row - 1, 0), col },
            ArrowRight: { row, col: Math.min(col + 1, lastCol) },
            ArrowLeft: { row, col: Math.max(col - 1, 0) },
            Home: { row, col: 0 },
            End: { row, col: lastCol },
        };
        const next = moves[ev.key];
        if (!next) {
            return;
        }
        ev.preventDefault();
        this.state.focus = next;
        this.getCellEl(next)?.focus();
    }

    async onScroll(ev) {
        const el = ev.currentTarget;
        if (!this.props.onLoadMore || this.state.loading) {
            return;
        }
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
            this.state.loading = true;
            try {
                await this.props.onLoadMore();
            } finally {
                this.state.loading = false;
            }
        }
    }

    toggleMenu(row) {
        this.state.menuRowId = this.state.menuRowId === row.id ? null : row.id;
    }

    runAction(action, row) {
        this.state.menuRowId = null;
        action.onSelect(row);
    }
}

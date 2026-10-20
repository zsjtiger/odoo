import { Component, proxy } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { DataTable } from "@advanced_ui/datatable/datatable";
import { Pager } from "@web/core/components/pager/pager";
import { buildFilterDomain, matchesDomain } from "@advanced_ui/datatable/filter_domain";

const STAGES = ["Prospecting", "Value Proposition", "Id. Decision Makers", "Negotiation"];

function formatDate(iso) {
    const [year, month, day] = iso.split("-");
    return `${Number(month)}/${Number(day)}/${year.slice(2)}`;
}

function formatAmount(value) {
    return `$${value.toLocaleString("en-US")}`;
}

function formatShortAmount(value) {
    return `$${Math.round(value / 1000)}k`;
}

const BASIC_COLUMNS = [
    { key: "name", label: "Opportunity Name", type: "link", sortable: true },
    { key: "account", label: "Account Name", sortable: true },
    { key: "closeDate", label: "Close Date", type: "date", sortable: true, format: formatDate },
    { key: "stage", label: "Stage", sortable: true },
    { key: "confidence", label: "Confidence", type: "number", sortable: true, format: (v) => `${v}%` },
    { key: "amount", label: "Amount", type: "number", sortable: true, format: formatShortAmount },
    { key: "contact", label: "Contact", type: "email", sortable: true },
];

const ADVANCED_COLUMNS = [
    { key: "name", label: "Name", type: "link", sortable: true },
    { key: "account", label: "Account Name", sortable: true },
    { key: "closeDate", label: "Close Date", type: "date", sortable: true, format: formatDate },
    { key: "stage", label: "Stage", sortable: true },
    { key: "confidence", label: "Confidence", type: "number", sortable: true, format: (v) => `${v}%` },
    { key: "amount", label: "Amount", type: "number", sortable: true, format: formatAmount },
    { key: "contact", label: "Contact", type: "email", sortable: true },
];

const ACCOUNTS = [
    ["Acme - 1,200 Widgets", "Acme", "2015-04-10", "Value Proposition", 70, 25000000, "jrogers@acme.com"],
    ["Acme - 200 Widgets", "Acme", "2015-01-31", "Prospecting", 30, 5000000, "bob@acme.com"],
    ["salesforce.com - 1,000 Licenses", "salesforce.com", "2015-01-31", "Id. Decision Makers", 60, 25000, "nathan@salesforce.com"],
    ["Acme - 800 Widgets", "Acme", "2018-06-11", "Value Proposition", 85, 970000, "jrogers@acme.com"],
    ["Acme - 744 Widgets", "Acme", "2017-04-15", "Prospecting", 56, 3110000, "bob@acme.com"],
];

const BASIC_ROWS = [
    ["Cloudhub", "Cloudhub", "2015-04-14", "Prospecting", 20, 25000, "jrogers@cloudhub.com"],
    ["Cloudhub + Anypoint Connectors", "Cloudhub", "2015-04-14", "Prospecting", 20, 25000, "jrogers@cloudhub.com"],
    ["Cloudhub", "Cloudhub", "2015-04-14", "Prospecting", 20, 25000, "jrogers@cloudhub.com"],
];

const FIELDS = ["name", "account", "closeDate", "stage", "confidence", "amount", "contact"];

function toRows(data, prefix) {
    return data.map((values, index) => {
        const row = { id: `${prefix}${index}` };
        values.forEach((value, i) => (row[FIELDS[i]] = value));
        return row;
    });
}

/**
 * Generates a deterministic batch of accounts, so the infinite list can load more.
 * @param {number} start index of the first generated row
 * @param {number} count number of rows to generate
 */
function generateRows(start, count) {
    const rows = [];
    for (let i = start; i < start + count; i++) {
        const day = (i % 27) + 1;
        const month = (i % 12) + 1;
        rows.push({
            id: `gen${i}`,
            name: `Acme - ${100 + i} Widgets`,
            account: "Acme",
            closeDate: `2018-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
            stage: STAGES[i % STAGES.length],
            confidence: (i * 7) % 100,
            amount: 1000 + ((i * 7919) % 500000),
            contact: "bob@acme.com",
            won: i % 3 === 0,
            partnerId: PARTNERS[i % PARTNERS.length].id,
        });
    }
    return rows;
}

const MAX_INFINITE_ROWS = 200;

const PARTNERS = [
    { id: 1, name: "Alice" },
    { id: 2, name: "Bob" },
    { id: 3, name: "Carol" },
];

/** Demo search for the relation filter: a real app would call the server here. */
async function searchPartners(term) {
    return PARTNERS.filter((partner) => partner.name.toLowerCase().includes(term.toLowerCase()));
}

const FILTER_COLUMNS = [
    { key: "name", label: "Name", filter: "text" },
    { key: "stage", label: "Stage", filter: "selection", selection: STAGES.map((stage) => [stage, stage]) },
    { key: "won", label: "Won", filter: "bool", format: (value) => (value ? "Yes" : "No") },
    { key: "closeDate", label: "Close Date", type: "date", filter: "date", format: formatDate },
    {
        key: "partnerId",
        label: "Partner",
        filter: "relation",
        searchRecords: searchPartners,
        format: (id) => PARTNERS.find((partner) => partner.id === id)?.name ?? "",
    },
    { key: "amount", label: "Amount", type: "number", filter: "number", format: formatAmount },
];

export class DataTableDemo extends Component {
    static template = "advanced_ui.DataTableDemo";
    static components = { DataTable, Pager };

    setup() {
        this.basicColumns = BASIC_COLUMNS;
        this.advancedColumns = ADVANCED_COLUMNS;
        this.fixedColumns = ADVANCED_COLUMNS.map((column, index) => ({
            ...column,
            fixed: index === 0 || index === 3,
        }));
        this.opportunities = toRows(BASIC_ROWS, "basic");
        this.accounts = toRows(ACCOUNTS, "account");
        this.largeRows = proxy([...this.accounts, ...generateRows(0, 30)]);
        this.infiniteRows = proxy(generateRows(0, 20));
        this.pagedRows = generateRows(0, 10);
        this.filterColumns = FILTER_COLUMNS;
        this.filterRows = generateRows(0, 30);
        this.filterState = proxy({ offset: 0, limit: 3, filters: {} });
        this.page = proxy({ offset: 0, limit: 3 });
        this.rowActions = [
            { label: "Edit", onSelect: (row) => console.info("Edit", row.name) },
            { label: "Delete", onSelect: (row) => console.info("Delete", row.name) },
        ];
    }

    get currentPage() {
        return this.pagedRows.slice(this.page.offset, this.page.offset + this.page.limit);
    }

    /** Pages are handled by the parent: DataTable only renders the rows it is given. */
    onPageUpdate({ offset, limit }) {
        this.page.offset = offset;
        this.page.limit = limit;
    }

    /** Rows matching the header filters. The total of the pager is the length of this list. */
    get filteredRows() {
        const domain = buildFilterDomain(FILTER_COLUMNS, this.filterState.filters);
        return this.filterRows.filter((row) => matchesDomain(row, domain));
    }

    get filterPage() {
        const { offset, limit } = this.filterState;
        return this.filteredRows.slice(offset, offset + limit);
    }

    onFilterChange(key, value) {
        this.filterState.filters[key] = value;
        this.filterState.offset = 0;
    }

    onFilterPageUpdate({ offset, limit }) {
        this.filterState.offset = offset;
        this.filterState.limit = limit;
    }

    async loadMore() {
        if (this.infiniteRows.length >= MAX_INFINITE_ROWS) {
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        this.infiniteRows.push(...generateRows(this.infiniteRows.length, 20));
    }
}

registry.category("actions").add("advanced_ui.datatable_demo", DataTableDemo);

/**
 * Helpers to turn the header filters of a DataTable into an Odoo domain.
 *
 * Each column opts in with `filter`. Its value depends on the type:
 * - "text": { operator, value }. Operators: "ilike", "=", "not ilike"
 * - "selection": array of the selected values, matched with "in"
 * - "relation": array of the selected records { id, name }, matched with "in" on their ids.
 *   Used for many2one, many2many and one2many columns.
 * - "bool": array of the selected booleans, matched with "in"
 * - "date" / "datetime": { operator, from, to } with "YYYY-MM-DD" dates. Operators:
 *   "between" (uses from and to), "=", "<" and ">" (use from). For "datetime" the
 *   bounds are the start and the end of the days in the user's timezone, in UTC.
 * - "number": { min, max }, each bound optional
 *
 * Empty values add no condition. Conditions are combined with AND, the implicit
 * operator of an Odoo domain.
 */

import { serializeDateTime } from "@web/core/data/l10n/dates";

const { DateTime } = luxon;

function isEmpty(value) {
    return value === undefined || value === null || value === "";
}

/**
 * Converts a "YYYY-MM-DD" filter bound to the value the server expects.
 * @param {"date" | "datetime"} filterType
 * @param {string} day
 * @param {"start" | "end"} edge
 */
function toServerValue(filterType, day, edge) {
    if (filterType === "date") {
        return day;
    }
    const datetime = DateTime.fromISO(day);
    return serializeDateTime(edge === "start" ? datetime.startOf("day") : datetime.endOf("day"));
}


/**
 * The value of a column filter when nothing is set.
 * @param {Object} column
 * @returns {Object|Array|null}
 */
export function emptyFilterValue(column) {
    switch (column.filter) {
        case "text":
            return { operator: "ilike", value: "" };
        case "selection":
        case "bool":
        case "relation":
            return [];
        case "date":
        case "datetime":
            return { operator: "between", from: "", to: "" };
        case "number":
            return { min: "", max: "" };
    }
    return null;
}

/**
 * Whether the value of a column filter restricts the rows.
 * @param {Object} column
 * @param {Object|Array|undefined} value
 * @returns {boolean}
 */
export function isFilterActive(column, value) {
    switch (column.filter) {
        case "text":
            return !isEmpty(value?.value);
        case "selection":
        case "bool":
        case "relation":
            return Boolean(value?.length);
        case "date":
        case "datetime":
            return !isEmpty(value?.from) || !isEmpty(value?.to);
        case "number":
            return !isEmpty(value?.min) || !isEmpty(value?.max);
    }
    return false;
}

/**
 * @param {Object[]} columns
 * @param {Object} filters values keyed by column key
 * @returns {Array} an Odoo domain
 */
export function buildFilterDomain(columns, filters) {
    const domain = [];
    for (const column of columns) {
        const value = filters[column.key];
        if (!isFilterActive(column, value)) {
            continue;
        }
        const key = column.key;
        switch (column.filter) {
            case "text":
                domain.push([key, value.operator || "ilike", value.value]);
                break;
            case "selection":
            case "bool":
                domain.push([key, "in", [...value]]);
                break;
            case "relation":
                domain.push([key, "in", value.map((record) => record.id)]);
                break;
            case "date":
            case "datetime": {
                const type = column.filter;
                const operator = value.operator || "between";
                if (operator === "between") {
                    if (!isEmpty(value.from)) {
                        domain.push([key, ">=", toServerValue(type, value.from, "start")]);
                    }
                    if (!isEmpty(value.to)) {
                        domain.push([key, "<=", toServerValue(type, value.to, "end")]);
                    }
                } else if (!isEmpty(value.from)) {
                    if (operator === "=" && type === "date") {
                        domain.push([key, "=", value.from]);
                    } else if (operator === "=") {
                        domain.push([key, ">=", toServerValue(type, value.from, "start")]);
                        domain.push([key, "<=", toServerValue(type, value.from, "end")]);
                    } else if (operator === "<") {
                        domain.push([key, "<", toServerValue(type, value.from, "start")]);
                    } else if (operator === ">") {
                        domain.push([key, ">", toServerValue(type, value.from, "end")]);
                    }
                }
                break;
            }
            case "number":
                if (!isEmpty(value.min)) {
                    domain.push([key, ">=", Number(value.min)]);
                }
                if (!isEmpty(value.max)) {
                    domain.push([key, "<=", Number(value.max)]);
                }
                break;
        }
    }
    return domain;
}

/**
 * Evaluates a domain built by buildFilterDomain on plain objects. Used when the
 * rows are not loaded from a model, such as in the demo and in the tests.
 * @param {Object} row
 * @param {Array} domain
 * @returns {boolean}
 */
export function matchesDomain(row, domain) {
    return domain.every(([key, operator, value]) => {
        const rowValue = row[key];
        switch (operator) {
            case "ilike":
                return String(rowValue ?? "").toLowerCase().includes(String(value).toLowerCase());
            case "not ilike":
                return !String(rowValue ?? "").toLowerCase().includes(String(value).toLowerCase());
            case "=":
                return rowValue === value;
            case "in":
                return value.includes(rowValue);
            case ">":
                return rowValue > value;
            case ">=":
                return rowValue >= value;
            case "<":
                return rowValue < value;
            case "<=":
                return rowValue <= value;
        }
        return true;
    });
}

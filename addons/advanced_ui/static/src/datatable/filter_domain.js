/**
 * Helpers to turn the header filters of a DataTable into an Odoo domain.
 *
 * A column opts in with `filter`:
 * - "text": substring match (ilike) on the value
 * - "selection": exact match, the column gives its options as `selection: [[value, label]]`
 * - "bool": exact match on true/false, the filter value is "true" or "false"
 * - "number": range, the filter value is { min, max } and each bound is optional
 * - "date" / "datetime": range, the filter value is { from, to } with "YYYY-MM-DD" dates.
 *   For "datetime" the bounds are the start and the end of those days in the user's
 *   timezone, converted to UTC for the server.
 *
 * Empty filter values add no condition. Domain conditions are combined with AND,
 * which is the implicit operator of an Odoo domain.
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
 * @param {Object[]} columns
 * @param {Object} filters values keyed by column key
 * @returns {Array} an Odoo domain
 */
export function buildFilterDomain(columns, filters) {
    const domain = [];
    for (const column of columns) {
        const value = filters[column.key];
        switch (column.filter) {
            case "text":
                if (!isEmpty(value)) {
                    domain.push([column.key, "ilike", value]);
                }
                break;
            case "selection":
                if (!isEmpty(value)) {
                    domain.push([column.key, "=", value]);
                }
                break;
            case "bool":
                if (!isEmpty(value)) {
                    domain.push([column.key, "=", value === "true"]);
                }
                break;
            case "date":
            case "datetime":
                if (!isEmpty(value?.from)) {
                    domain.push([column.key, ">=", toServerValue(column.filter, value.from, "start")]);
                }
                if (!isEmpty(value?.to)) {
                    domain.push([column.key, "<=", toServerValue(column.filter, value.to, "end")]);
                }
                break;
            case "number":
                if (!isEmpty(value?.min)) {
                    domain.push([column.key, ">=", Number(value.min)]);
                }
                if (!isEmpty(value?.max)) {
                    domain.push([column.key, "<=", Number(value.max)]);
                }
                break;
        }
    }
    return domain;
}

/**
 * Evaluates a domain built by buildFilterDomain on plain objects. Used when the
 * rows are not loaded from a model, such as in the demo.
 * @param {Object} row
 * @param {Array} domain
 * @returns {boolean}
 */
export function matchesDomain(row, domain) {
    return domain.every(([key, operator, value]) => {
        const rowValue = row[key];
        switch (operator) {
            case "ilike":
                return String(rowValue).toLowerCase().includes(String(value).toLowerCase());
            case "=":
                return rowValue === value;
            case ">=":
                return rowValue >= value;
            case "<=":
                return rowValue <= value;
        }
        return true;
    });
}

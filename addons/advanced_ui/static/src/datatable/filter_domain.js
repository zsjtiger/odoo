/**
 * Helpers to turn the header filters of a DataTable into an Odoo domain.
 *
 * A column opts in with `filter`:
 * - "text": substring match (ilike) on the value
 * - "selection": exact match, the column gives its options as `selection: [[value, label]]`
 * - "bool": exact match on true/false, the filter value is "true" or "false"
 * - "number": range, the filter value is { min, max } and each bound is optional
 *
 * Empty filter values add no condition. Domain conditions are combined with AND,
 * which is the implicit operator of an Odoo domain.
 */

function isEmpty(value) {
    return value === undefined || value === null || value === "";
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

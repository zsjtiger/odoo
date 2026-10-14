/**
 * 列表与看板的排序与筛选: 决定哪些字段可以排序/筛选, 以及如何转换为服务端的 order 与 domain.
 */

/** 可排序的字段类型 (二进制、一对多、文本等不能排序) */
const SORTABLE_TYPES = ["char", "integer", "float", "monetary", "date", "datetime", "boolean", "selection", "many2one"];

/** 可筛选的字段类型, 与 buildFilterDomain 中的规则对应 */
const FILTERABLE_TYPES = ["char", "integer", "float", "monetary", "boolean", "selection", "many2one"];

/**
 * @param {{ name: string, field: { type: string, string?: string, selection?: any[] } | undefined }[]} columns
 * @param {string[]} types
 * @returns {{ name: string, label: string, type: string, selection?: any[] }[]}
 */
function pick(columns, types) {
    return columns
        .filter((column) => column.field && types.includes(column.field.type))
        .map((column) => ({
            name: column.name,
            label: column.field.string || column.name,
            type: column.field.type,
            selection: column.field.selection,
        }));
}

export function sortableFields(columns) {
    return pick(columns, SORTABLE_TYPES);
}

export function filterableFields(columns) {
    return pick(columns, FILTERABLE_TYPES);
}

/**
 * 筛选条件 -> 服务端 domain 的一个条件. 没有值时不加条件.
 *  - 文本与 many2one: 包含 (ilike, many2one 按名称匹配)
 *  - 选择、布尔、数值: 等于
 *
 * @param {{ name: string, type: string, value: string } | null} filter
 * @returns {any[]} domain 的条件列表(0 或 1 个)
 */
export function buildFilterDomain(filter) {
    if (!filter || filter.value === "" || filter.value === undefined || filter.value === null) {
        return [];
    }
    const { name, type, value } = filter;
    switch (type) {
        case "char":
        case "many2one":
            return [[name, "ilike", value]];
        case "boolean":
            return [[name, "=", value === "true"]];
        case "integer":
            return [[name, "=", parseInt(value, 10)]];
        case "float":
        case "monetary":
            return [[name, "=", parseFloat(value)]];
        default:
            return [[name, "=", value]];
    }
}

/**
 * 排序 -> 服务端 order 字符串, 如 "name DESC" (方向使用大写, 与 ORM 的写法一致)
 *
 * @param {{ name: string, dir: "asc" | "desc" } | null} sort
 */
export function orderString(sort) {
    return sort && sort.name ? `${sort.name} ${sort.dir.toUpperCase()}` : "";
}

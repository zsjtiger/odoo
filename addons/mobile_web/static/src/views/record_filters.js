/**
 * 列表与看板的排序与筛选: 决定哪些字段可以排序/筛选, 以及如何转换为服务端的 order 与 domain.
 */

/** 可排序的字段类型 (二进制、一对多、文本等不能排序) */
const SORTABLE_TYPES = ["char", "integer", "float", "monetary", "date", "datetime", "boolean", "selection", "many2one"];

/** 可搜索 (顶部搜索的建议) 的字段类型, 与 search_facets 中的操作符规则对应 */
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

/** arch 中的标记属性取值为真: "1" / "true" / "True" */
function isTruthyAttr(value) {
    return value === "1" || value === "true" || value === "True";
}

/**
 * 按 arch 中的标记属性 (sortable / filterable) 选出列.
 * 默认所有列都可用; 如果有列标记为真, 则只有标记为真的列可用; 标记为 "0" 的列始终排除.
 *
 * @param {{ name: string, attrs?: Object<string, string>, field: any }[]} columns
 * @param {string} attr
 */
function markedColumns(columns, attr) {
    const valueOf = (column) => column.attrs && column.attrs[attr];
    // 只有明确标记为真的列才会开启白名单; 仅写 "0" 只排除该列, 其余仍然可用
    const anyMarked = columns.some((column) => isTruthyAttr(valueOf(column)));
    return columns.filter((column) => {
        const value = valueOf(column);
        if (value !== undefined) {
            return isTruthyAttr(value);
        }
        return !anyMarked;
    });
}

/**
 * 可排序的字段: 见 markedColumns, 使用 sortable 属性
 *
 * @param {{ name: string, attrs?: Object<string, string>, field: any }[]} columns
 */
export function sortableFields(columns) {
    return pick(markedColumns(columns, "sortable"), SORTABLE_TYPES);
}

/**
 * 可筛选的字段: 见 markedColumns, 使用 filterable 属性
 *
 * @param {{ name: string, attrs?: Object<string, string>, field: any }[]} columns
 */
export function filterableFields(columns) {
    return pick(markedColumns(columns, "filterable"), FILTERABLE_TYPES);
}

/**
 * 排序 -> 服务端 order 字符串, 如 "name DESC" (方向使用大写, 与 ORM 的写法一致)
 *
 * @param {{ name: string, dir: "asc" | "desc" } | null} sort
 */
export function orderString(sort) {
    return sort && sort.name ? `${sort.name} ${sort.dir.toUpperCase()}` : "";
}

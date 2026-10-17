/**
 * 顶部搜索的条件 (facet) 与建议, 参考 PC 端的搜索栏.
 *
 * facet: { id, name, label, type, value, display, operator? }
 *   - name / label: 字段名 / 字段显示名
 *   - value: 用于查询的值 (many2one 为 id, selection 为枚举值)
 *   - display: 胶囊上显示的文字
 *   - operator: 指定操作符时使用 (如 many2one 按名称包含搜索)
 */

/** 数值类型: 输入的文字必须能解析为数字才可以按等于搜索 */
const NUMBER_TYPES = ["integer", "float", "monetary"];

/**
 * 单个条件 -> domain 的一个叶子条件, 操作符与 PC 端一致:
 * 文本 ilike, many2one 按 id 等于, 选择/布尔/数值 等于
 *
 * @param {Object} facet
 * @returns {any[]}
 */
export function facetLeaf(facet) {
    const { name, type, value, operator } = facet;
    if (operator) {
        return [name, operator, value];
    }
    switch (type) {
        case "char":
        case "text":
            return [name, "ilike", value];
        case "boolean":
            return [name, "=", value === true || value === "true"];
        case "integer":
            return [name, "=", parseInt(value, 10)];
        case "float":
        case "monetary":
            return [name, "=", parseFloat(value)];
        default:
            // many2one 的 id 与选择类的枚举值
            return [name, "=", value];
    }
}

/**
 * 所有条件合并为 domain: 同一字段的多个条件之间为"或", 不同字段之间为"且" (与 PC 端一致)
 *
 * @param {Object[]} facets
 * @returns {any[]}
 */
export function facetsDomain(facets) {
    const groups = new Map();
    for (const facet of facets) {
        groups.set(facet.name, [...(groups.get(facet.name) || []), facetLeaf(facet)]);
    }
    const domain = [];
    for (const leaves of groups.values()) {
        // 同一字段的 n 个条件用 n-1 个 "|" 连接; 顶层的多个表达式默认为"且"
        for (let i = 1; i < leaves.length; i++) {
            domain.push("|");
        }
        domain.push(...leaves);
    }
    return domain;
}

/**
 * 建议行: 每个可搜索字段一行, 输入的文字为搜索值
 *  - char / text: 点击即按包含搜索
 *  - many2one: 点击即按名称包含搜索; 展开箭头后列出候选记录, 按 id 搜索
 *  - 数值: 文字为数字时点击即按等于搜索
 *  - selection: 展开后列出 (按文字过滤的) 选项
 *
 * @param {string} text 输入的文字
 * @param {{ name: string, label: string, type: string, selection?: any[] }[]} fields 可搜索的字段
 * @param {Object<string, any[]>} options 已加载的候选项, 按字段名: many2one 为 [id, name], selection 为 [value, label]
 * @param {string|null} expanded 当前展开的字段名
 * @returns {{ key: string, name: string, label: string, type: string, text: string, expandable: boolean, expanded: boolean, options: any[] }[]}
 */
export function suggestionRows(text, fields, options = {}, expanded = null) {
    const value = (text || "").trim();
    if (!value) {
        return [];
    }
    const rows = [];
    for (const field of fields) {
        const base = { name: field.name, label: field.label, type: field.type, text: value };
        if (field.type === "char" || field.type === "text") {
            rows.push({ ...base, key: `${field.name}:text`, expandable: false, expanded: false, options: [] });
        } else if (field.type === "many2one") {
            rows.push({
                ...base,
                key: `${field.name}:text`,
                expandable: true,
                expanded: expanded === field.name,
                options: expanded === field.name ? options[field.name] || [] : [],
            });
        } else if (NUMBER_TYPES.includes(field.type)) {
            if (!Number.isNaN(Number(value))) {
                rows.push({ ...base, key: `${field.name}:text`, expandable: false, expanded: false, options: [] });
            }
        } else if (field.type === "selection") {
            const matches = (field.selection || []).filter(([, label]) =>
                String(label).toLowerCase().includes(value.toLowerCase())
            );
            if (matches.length) {
                rows.push({
                    ...base,
                    key: `${field.name}:options`,
                    expandable: true,
                    expanded: expanded === field.name,
                    options: expanded === field.name ? matches : [],
                });
            }
        }
    }
    return rows;
}

/**
 * 由建议行的一个候选项生成 facet
 *
 * @param {{ name: string, label: string, type: string, text: string }} row
 * @param {{ value: any, display: string }} [option] 展开后选择的候选项; 不传时使用文字
 * @param {number} id
 */
export function facetFromRow(row, option, id) {
    if (row.type === "many2one" && option) {
        return { id, name: row.name, label: row.label, type: row.type, value: option.value, display: option.display };
    }
    if (row.type === "many2one") {
        return { id, name: row.name, label: row.label, type: row.type, value: row.text, display: row.text, operator: "ilike" };
    }
    if (row.type === "selection") {
        return { id, name: row.name, label: row.label, type: row.type, value: option.value, display: option.display };
    }
    if (NUMBER_TYPES.includes(row.type)) {
        const number = row.type === "integer" ? parseInt(row.text, 10) : parseFloat(row.text);
        return { id, name: row.name, label: row.label, type: row.type, value: number, display: row.text };
    }
    return { id, name: row.name, label: row.label, type: row.type, value: row.text, display: row.text };
}

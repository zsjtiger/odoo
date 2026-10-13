/**
 * 把视图 arch(XML 字符串) 解析为简单的节点树, 便于渲染
 *
 * @typedef {Object} ArchNode
 * @property {string} tag
 * @property {Object<string, string>} attrs
 * @property {ArchNode[]} children
 */

/**
 * @param {string} arch
 * @returns {ArchNode}
 */
export function parseArch(arch) {
    const doc = new DOMParser().parseFromString(arch, "text/xml");
    return toNode(doc.documentElement);
}

function toNode(el) {
    const attrs = {};
    for (const attr of el.attributes) {
        attrs[attr.name] = attr.value;
    }
    const children = [];
    for (const child of el.childNodes) {
        if (child.nodeType === Node.ELEMENT_NODE) {
            children.push(toNode(child));
        }
    }
    return { tag: el.tagName, attrs, children };
}

/**
 * 收集视图中用到的所有字段名(包括嵌套在 group/notebook/kanban 模板中的字段)
 *
 * @param {ArchNode} node
 * @param {Set<string>} [names]
 * @returns {Set<string>}
 */
export function collectFieldNames(node, names = new Set()) {
    if (node.tag === "field" && node.attrs.name) {
        names.add(node.attrs.name);
    }
    for (const child of node.children) {
        collectFieldNames(child, names);
    }
    return names;
}

/**
 * 字段节点是否应隐藏(arch 中 invisible="1" 或 "True")
 *
 * @param {ArchNode} node
 * @returns {boolean}
 */
export function isInvisible(node) {
    const value = node.attrs.invisible;
    return value === "1" || value === "True" || value === "true";
}

/**
 * 列表/看板中不展示的列: 拖拽手柄, column_invisible, 以及 invisible
 *
 * @param {ArchNode} node
 * @returns {boolean}
 */
export function isHiddenColumn(node) {
    const hidden = node.attrs.column_invisible;
    return isInvisible(node) || node.attrs.widget === "handle" || hidden === "1" || hidden === "True" || hidden === "true";
}

// 标题列优先选择文本类字段: 列表中第一列常常是日期或数字(例如 Users 列表的 login_date)
const TITLE_TYPES = ["char", "many2one", "text", "selection"];

/**
 * 从列表/看板的列中选出标题列, 其余作为副标题
 *
 * @param {Object[]} columns  {name, attrs, field}
 * @returns {{primary: Object|null, secondary: Object[]}}
 */
export function splitColumns(columns) {
    const index = columns.findIndex((c) => c.field && TITLE_TYPES.includes(c.field.type));
    const primaryIndex = index >= 0 ? index : 0;
    const primary = columns[primaryIndex] || null;
    const secondary = columns.filter((_, i) => i !== primaryIndex);
    return { primary, secondary };
}

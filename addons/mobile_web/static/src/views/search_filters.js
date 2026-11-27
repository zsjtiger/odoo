import { parseArch } from "@mobile_web/views/arch";

/**
 * 搜索视图中的筛选项 (<filter domain="...">): 返回 [{ key, label, domain }].
 * 分组(group_by)等没有 domain 的项不属于筛选, 忽略.
 *
 * @param {string|undefined} arch  搜索视图的 arch
 * @returns {{ key: string, label: string, domain: string }[]}
 */
export function parseSearchFilters(arch) {
    if (!arch) {
        return [];
    }
    const filters = [];
    const walk = (node) => {
        for (const child of node.children) {
            if (child.tag === "filter" && child.attrs.domain) {
                const key = child.attrs.name || `filter_${filters.length}`;
                filters.push({ key, label: child.attrs.string || key, domain: child.attrs.domain });
            } else if (child.children?.length) {
                walk(child);
            }
        }
    };
    walk(parseArch(arch));
    return filters;
}

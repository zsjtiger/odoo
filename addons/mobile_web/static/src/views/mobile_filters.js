/**
 * 移动端自定义筛选面板的条件组合 (配置来自模型的 dynamic_filter_config):
 *  - 同一分组中选中的选项 (及选中的卡片) 之间为或
 *  - 不同分组之间为且
 *
 * @param {{ name: string, options: { key: string, domain: any[] }[], cards?: { field: string } }[]} sections
 * @param {{ options: string[], cards: Object<string, number[]> }} selected
 * @returns {any[]} 服务端的 domain
 */
export function mobileFilterDomain(sections, selected) {
    let domain = [];
    for (const section of sections) {
        const parts = section.options.filter((option) => selected.options.includes(option.key)).map((option) => option.domain);
        const ids = section.cards ? selected.cards[section.cards.field] || [] : [];
        if (ids.length) {
            parts.push([[section.cards.field, "in", ids]]);
        }
        if (!parts.length || parts.some((part) => !part.length)) {
            // 没有选择, 或选择了"不限制"的条件: 该分组不做限制
            continue;
        }
        domain = [...domain, ...orOf(parts)];
    }
    return domain;
}

/** 多个条件的且: 使用前缀表示 */
function andOf(terms) {
    return terms.length <= 1 ? terms : [...Array(terms.length - 1).fill("&"), ...terms];
}

/** 多个条件组的或: 使用前缀表示 */
function orOf(parts) {
    if (parts.length === 1) {
        return andOf(parts[0]);
    }
    return [...Array(parts.length - 1).fill("|"), ...parts.flatMap((part) => andOf(part))];
}

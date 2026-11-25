/**
 * 读取主题颜色. 颜色定义在样式令牌 (styles/00_tokens.scss) 中, 以 CSS 变量导出,
 * 脚本通过这里读取, 以便主题模块修改颜色后, 脚本里的颜色 (调色板等) 同时改变.
 * 读不到时使用给定的默认值 (例如在没有加载样式的测试环境中).
 */

/**
 * @param {string} name 不含 -- 前缀的变量名, 例如 "m-calendar-0"
 * @param {string} fallback 默认值
 * @returns {string}
 */
export function cssVar(name, fallback) {
    if (typeof document === "undefined" || !document.documentElement) {
        return fallback;
    }
    const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
    return value || fallback;
}

/**
 * 调色板中的第 index 个颜色 (循环取色). 调色板的颜色为 --m-<prefix>-<n>.
 *
 * @param {string} prefix 例如 "calendar" 或 "home"
 * @param {string[]} defaults 默认调色板
 * @param {number} index
 * @returns {string}
 */
export function paletteColor(prefix, defaults, index) {
    const i = ((index % defaults.length) + defaults.length) % defaults.length;
    return cssVar(`m-${prefix}-${i}`, defaults[i]);
}

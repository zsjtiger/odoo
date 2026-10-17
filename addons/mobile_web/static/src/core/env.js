/**
 * 取得组件的 env. Owl 的类型声明中 Component 没有 env 属性, 这里集中做一次类型转换,
 * 避免在各个组件中分散地转换.
 *
 * @param {object} component
 * @returns {Record<string, any>}
 */
export function envOf(component) {
    return /** @type {any} */ (component).env;
}

/**
 * Owl 的类型声明无法表达组件类 (ComponentConstructor), 这里集中做一次类型转换
 *
 * @param {Function} ComponentClass
 * @returns {any}
 */
export function asComponent(ComponentClass) {
    return /** @type {any} */ (ComponentClass);
}

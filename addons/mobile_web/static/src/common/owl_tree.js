/**
 * 在子组件树中查找第一个满足条件的组件. web 的视图控制器位于 View 内部, 通过 Owl 的
 * 组件树定位(与 web/static/src/core/owl/utils.js 中的 render 一样使用 __owl__)
 *
 * @param {Component} component
 * @param {(c: Component) => boolean} predicate
 * @returns {Component|null}
 */
export function findDescendant(component, predicate) {
    const children = component.__owl__?.children || {};
    for (const node of Object.values(children)) {
        const child = node.component || node;
        if (predicate(child)) {
            return child;
        }
        const found = findDescendant(child, predicate);
        if (found) {
            return found;
        }
    }
    return null;
}

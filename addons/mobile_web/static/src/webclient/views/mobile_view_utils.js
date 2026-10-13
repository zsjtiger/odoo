/**
 * 动作的视图列表: 没有明确指定 views 时, 使用 view_mode 推导
 *
 * @param {Object} action
 * @returns {Array<[number|false, string]>}
 */
export function getActionViews(action) {
    if (action.views && action.views.length) {
        return [...action.views];
    }
    return (action.view_mode || "list,form").split(",").map((viewMode) => [false, viewMode.trim()]);
}

/**
 * 动作是否包含 form 视图
 *
 * @param {Object} action
 * @returns {boolean}
 */
export function hasFormView(action) {
    return getActionViews(action).some((v) => v[1] === "form");
}

/**
 * URL 状态中使用的动作标识: 优先 path, 否则 id
 *
 * @param {Object} action
 * @returns {string|number}
 */
export function getStateAction(action) {
    return action.path ? action.path : action.id;
}

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

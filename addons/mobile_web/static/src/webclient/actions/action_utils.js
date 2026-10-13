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
 * 构造路由状态, 与 router 联动. 移动端没有 PC 端的面包屑, 所以 actionStack 始终只有一层.
 * resId 为假值时不写入状态
 *
 * @param {Object} action
 * @param {number|string|false} [resId]
 * @returns {Object} RouterState
 */
export function buildRouteState(action, resId = false) {
    const stateAction = getStateAction(action);
    const state = {
        action: stateAction,
        _isMobile: true,
    };
    if (resId) {
        state.resId = resId;
    }
    state.actionStack = [{
        action: stateAction,
        _isMobile: true,
        ...(resId ? { resId } : {}),
    }];
    return state;
}

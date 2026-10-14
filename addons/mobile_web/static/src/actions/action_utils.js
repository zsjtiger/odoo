/**
 * 动作的视图列表, 顺序与 web 一致: 以 view_mode 为准, 视图 id 从 action.views 中按类型取.
 * 服务端返回的 views 顺序取决于 ir.actions.act_window.view 的 sequence, 不一定与 view_mode 相同
 * (例如 view_mode 为 kanban,list,form 而 sequence 为 list 优先), 因此不能直接使用 action.views 的顺序.
 *
 * @param {Object} action
 * @returns {Array<[number|false, string]>}
 */
export function getActionViews(action) {
    if (!action.view_mode) {
        return action.views && action.views.length
            ? [...action.views]
            : [[false, "list"], [false, "form"]];
    }
    const viewIdByType = new Map((action.views || []).map(([id, type]) => [type, id]));
    return action.view_mode.split(",").map((viewMode) => {
        const type = viewMode.trim();
        return [viewIdByType.get(type) || false, type];
    });
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

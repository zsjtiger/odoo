import { omit } from "@web/core/utils/objects";
import { isNumeric } from "@web/core/utils/strings";
import { router as _router, startRouter } from '@web/core/services/browser/router';


// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------


/**
 * @typedef {Object} Router
 * @property {RouterState} current
 * @property {function} stateToUrl
 * @property {function} urlToState
 * @property {function(RouterState): void} pushState
 * @property {function} cancelPushes
 * @property {function(string): void} addLockedKey
 * @property {function(string): void} hideKeyFromUrl
 * @property {Boolean} skipLoad
 */

/**
 * RouterState除了未标注的属性外, 仍可附加其他属性:
 * 例如: `127.0.0.1:8069/mobile_web/action-11?name=123&age=321`, 经mobileUrlToState转换后,
 * RouterState 为 `{name: 123, age: 321, action: 11, actionStack: Array(1)}`
 *
 * @typedef {Object} RouterState
 * @property {number|string} [action] action信息: `ir.actions.action.id` or `ir.actions.action.path`
 * @property {string} [model] model名: `ir.model.model`
 * @property {number} [active_id]
 * @property {number|string} [resId] 记录id
 * @property {StateActionStack} [actionStack]
 * @property {Boolean} [_isMobile]
 */

/** @typedef {StateInfo[]} StateActionStack */

/**
 * @typedef {Object} StateInfo
 * @property {number|string} [action] action信息: `ir.actions.action.id` or `ir.actions.action.path`
 * @property {string} [model] model名: `ir.model.model`
 * @property {number} [active_id]
 * @property {number|string} [resId] 记录id
 * @property {Boolean} [_isMobile]
 */


// -----------------------------------------------------------------------------
// Mobile Router Functions
// -----------------------------------------------------------------------------


// web 通过 router 对象提供 state <-> url 的转换(可被替换), 这里保存 web 的原始实现
const webUrlToState = _router.urlToState;
const webStateToUrl = _router.stateToUrl;

/**
 *
 * @param {URL} urlObj
 * @return {RouterState}
 */
export function mobileUrlToState(urlObj) {
    /** @type {RouterState} */
    const webState = webUrlToState(urlObj);

    if (webState && webState.hasOwnProperty('actionStack')) {
        return webState;
    }

    // 如果为空对象或者对象里没有'actionStack'属性, 代表web模块的解析失败, 接下来是手机端的解析逻辑
    const [prefix, ...splitPath] = urlObj.pathname.split("/").filter(Boolean);
    if (prefix === 'mobile_web') {
        // 下面的解析逻辑, 与web/static/core/browser/router.js相同
        const actionParts = [...splitPath.entries()].filter(
            ([_, part]) => !isNumeric(part) && part !== "new"
        );

        const actions = [];
        for (const [i, part] of actionParts) {
            /** @type {StateInfo} */
            const action = {};
            const [left, right] = [splitPath[i - 1], splitPath[i + 1]];
            if (isNumeric(left)) {
                action.active_id = parseInt(left);
            }

            if (right === "new") {
                action.resId = "new";
            } else if (isNumeric(right)) {
                action.resId = parseInt(right);
            }

            if (part.startsWith("action-")) {   
                const actionId = part.slice(7);
                action.action = isNumeric(actionId) ? parseInt(actionId) : actionId;
            } else if (part.startsWith("m-")) {
                action.model = part.slice(2);
            } else if (part.includes(".")) {
                action.model = part;
            } else {
                action.action = part;
            }
            
            // 此属性为stateToUrl方法服务
            action._isMobile = true;

            if (action.resId && action.action) {
                actions.push(omit(action, "resId"));
            }

            if (action.action || action.resId || i === splitPath.length - 1) {
                actions.push(action);
            }
        }

        const activeAction = actions.at(-1);
        if (activeAction) {
            Object.assign(webState, activeAction);
            webState.actionStack = actions;
        }
    }

    return webState;
}


/**
 * 这里只需要把web里的`stateToUrl`方法的返回值的前缀(`/odoo` 或 `/scoped_app`)换成`/mobile_web`即可
 * 
 * @param {RouterState} state 
 * @return {string}
 */
export function mobileStateToUrl(state) {
    /** @type {string} */
    const webUrl = webStateToUrl(state);

    if (state?._isMobile) {
        return webUrl.replace(/^\/(odoo|scoped_app)(?=\/|\?|$)/, '/mobile_web');
    }

    return webUrl;
}


// -----------------------------------------------------------------------------
// mobile_web JS Module Scripts
// -----------------------------------------------------------------------------


// 替换工具方法
_router.stateToUrl = mobileStateToUrl;
_router.urlToState = mobileUrlToState;

// 重新执行startRouter, 确保覆盖生效, 并且刷新web闭包内的state变量
startRouter();

// 通过'@web/core/browser/router'提供的router变量, 屏蔽`_isMobile`属性
_router.hideKeyFromUrl('_isMobile');

/** @type {Router} */
export const router = _router;

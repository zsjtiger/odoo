import { KeepLast } from "@web/core/utils/concurrency";

import { router as _router } from "@mobile_web/core/browser/router";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { MobileActWindowController } from "@mobile_web/views/act_window_controller";
import { buildRouteState } from "@mobile_web/webclient/actions/action_utils";
import { loadAction, loadPageActions } from "@mobile_web/webclient/actions/action_loader";


// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------


/** @typedef {number|false} ActionId */
/** @typedef {Object} ActionDescription */
/** @typedef {"current" | "fullscreen" | "new" | "main" | "self" | "inline"} ActionMode */
/** @typedef {string} ActionTag */
/** @typedef {string} ActionXMLId */
/** @typedef {Object} Context */
/** @typedef {Function} CallableFunction */
/** @typedef {string} ViewType */
/** @typedef { ActionId|ActionXMLId|ActionTag|ActionDescription } ActionRequest */  // TODO: ActionTag是ir.action.client的东西

/**
 * @typedef {object} Action
 * 
 * // from `ir.actions.actions`
 * @property {number|false} binding_model_id
 * @property {"action"|"report"} binding_type
 * @property {string} binding_view_types such as `list,form`
 * @property {string} display_name
 * @property {string|false} help HTML string
 * @property {number} id
 * @property {string} name
 * @property {"ir.actions.act_window"|"ir.actions.act_url"|"ir.actions.server"|"ir.actions.client"|"ir.actions.report"|"ir.actions.mobile_page""} type
 * @property {ActionXMLId} xml_id
 * @property {string|false} path
 * @property {number|false} binding_mobile_page
 * 
 * // from python `env['ir.actions.act_window']._get_readable_fields()`
 * @property {number[]} embedded_action_ids
 * @property {string|false} context
 * @property {string|false} mobile_view_mode
 * @property {string|false} domain
 * @property {boolean} filter
 * @property {object[]} groups_id
 * @property {number} limit
 * @property {number|false} res_id
 * @property {string} res_model
 * @property {number|false} search_view_id
 * @property {ActionMode} target
 * @property {number|false} view_id
 * @property {string} view_mode
 * @property {Array[Array[number|false, string]]} views
 * 
 * // from python `env['ir.actions.mobile_page']._get_readable_fields()`
 * @property {MobilePageInfo} binding_mobile_page
 */

/** 
 * @typedef {Object} CurrentActionInfo 当前Action内可执行的其他Action
 * @property {string} name
 * @property {number} action_id
 * @property {number} svg_icon_href
 */

/** @typedef {[mobilePageId, mobilePageName, mobilePageComponentId] | false} MobilePageInfo */
/** @typedef {number} mobilePageId */
/** @typedef {string} mobilePageName */
/** @typedef {string} mobilePageComponentId */

/**
 * @typedef {object} ActionContainerEventInfo
 * @property {Component} Component
 * @property {object} [componentProps]
 * @property {CurrentActionInfo[]} [currentActions]
 */


// -----------------------------------------------------------------------------
// Errors
// -----------------------------------------------------------------------------


export class MobilePageNotFoundError extends Error {};


// -----------------------------------------------------------------------------
// ActionManager (Service)
// -----------------------------------------------------------------------------


export function makeMobileActionManager(env, router = _router) {
    /** @type {Action} 记录一下当前正在展示的action */
    let currentAction;

    // ---------------------------------------------------------------------------
    // public API
    // ---------------------------------------------------------------------------

    /**
     * 统一的对外调用接口
     *
     * @param {ActionRequest} actionRequest
     * @param {Object} options
     * @returns {Promise<void>}
     */
    async function doAction(actionRequest, options = {}) {
        const keepLast = new KeepLast();  // TODO: 使用keeplast的这个行为，是从web模块拷贝过来的

        // 加载action
        const actionPromise = loadAction(actionRequest, options.additionalContext);
        let action = await keepLast.add(actionPromise);

        // 执行action
        switch (action.type) {
            // 加载手机端的页面
            case "ir.actions.mobile_page":
                return _executeActionMobilePage(action, options)

            // 兼容PC端的ActWindow, 在移动端渲染List/Form视图
            case "ir.actions.act_window":
                return _executeActionActWindow(action, options)

            // TODO: 其他action的支持
            default:
                console.log("TODO")
        }
    };

    // ---------------------------------------------------------------------------
    // Action Handler
    // ---------------------------------------------------------------------------

    /**
     * `ir.actions.mobile_page` Action Handler
     * 
     * 拿到action的信息，然后获取对应的component，trigger 一个event，通知ActionContainer更新component
     * 
     * @param {Action} action
     * @param {object} options 
     * @throws {MobilePageNotFoundError}
     */
    async function _executeActionMobilePage(action, options = {}){
        /** @type {MobilePageInfo} */
        const pageInfo = action.binding_mobile_page;

        if (!pageInfo) {
            const msg = 'not found binding_mobile_page data in aciton';
            throw new MobilePageNotFoundError(msg);
        }

        const [mobilePageId, mobilePageName, mobilePageComponentId] = pageInfo;
        if (!mobilePageComponentId) {
            const msg = `pageInfo: ${pageInfo} error mobilePageComponentId`;
            throw new MobilePageNotFoundError(msg);
        }

        const mobilePageComponent = mobilePageRegistry.get(mobilePageComponentId);
        /** @type {Array[CurrentActionInfo]} currentActions */
        const currentActions = await loadPageActions(mobilePageId);

        /** @type {ActionContainerEventInfo} */
        const actionContainerInfo = {
            'Component': mobilePageComponent,
            'currentActions': currentActions,
        };

        // 1. 触发ActionContainer更新
        env.bus.trigger("ACTION_MANAGER:UPDATE", actionContainerInfo);

        // 2. 触发NavBar Title更新
        env.bus.trigger("NAVBAR_TITLE:UPDATE", {
            title: mobilePageName ? mobilePageName : `Page-${mobilePageId}`,
        });

        pushState(action);
    };

    /**
     * `ir.actions.act_window` Action Handler
     *
     * 使用 MobileActWindowController 包装桌面端 View 组件, 在移动端渲染 List/Form 视图
     *
     * @param {Action} action
     * @param {object} options
     */
    async function _executeActionActWindow(action, options = {}) {
        const state = router.current || {};
        const resId = options.resId !== undefined ? options.resId : state.resId;

        /** @type {ActionContainerEventInfo} */
        const actionContainerInfo = {
            'Component': MobileActWindowController,
            'componentProps': {
                action: Object.assign({}, action),
                resId,
                additionalContext: options.additionalContext || {},
            },
        };

        // 1. 触发ActionContainer更新
        env.bus.trigger("ACTION_MANAGER:UPDATE", actionContainerInfo);

        // 2. 触发NavBar Title更新
        env.bus.trigger("NAVBAR_TITLE:UPDATE", {
            title: action.display_name ? action.display_name : 'CrossNow',
        });

        pushState(action, resId);
    };

    // ---------------------------------------------------------------------------
    // Misc Tool Function
    // ---------------------------------------------------------------------------

    /**
     * 与router联动, 将当前的action转换为state, 调用router更新路由
     * 由于Mobile端没有PC端的面包屑, 所以这里的State仅保存当前的state, 也就是说actionStack始终长度为1
     * 首先使用action.path字段, 其次使用action.id字段
     *
     * @param {Action} action
     * @param {number|string|false} [resId]
     */
    function pushState(action, resId = false) {
        router.pushState(buildRouteState(action, resId));
    };

    // ---------------------------------------------------------------------------
    // 返回ActionManager对象
    // ---------------------------------------------------------------------------

    return {
        doAction,
    };
};


// -----------------------------------------------------------------------------
// ActionManager (Service) Registry
// -----------------------------------------------------------------------------


export const mobileActionService = {
    dependencies: [],
    start(env) {
        return makeMobileActionManager(env);
    },
};


// 注册在 main.js 中完成(见 mobileActionService), 避免测试包加载顺序导致重复注册

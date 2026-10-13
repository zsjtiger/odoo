import { markup, Component, xml } from "@crossnow/owl";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { rpc, rpcBus } from "@web/core/network/rpc";
import { session } from "@web/session";
import { user } from "@web/core/user";
import { makeContext } from "@web/core/context";
import { Deferred, KeepLast } from "@web/core/utils/concurrency";

import { router as _router } from '@mobile_web/core/browser/router';
import { mobilePageRegistry } from '@mobile_web/pages/common/page_registry';
import { MobileActWindowController } from '@mobile_web/webclient/views/mobile_act_window_controller';


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
        const actionPromise = _loadAction(actionRequest, options.additionalContext);
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
        const currentActions = await _loadPageActions(mobilePageId);

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
     * 将actionRequest加载为Action
     *
     * @param {ActionRequest} actionRequest
     * @param {Object} context
     * @returns {Promise<Action>}
     * @private
     */
    async function _loadAction(actionRequest, context = {}) {
        // TODO: 实现ir.actions.client
        // TODO: 实现web中的actionCache功能(如需要)

        if (typeof actionRequest === "string" || typeof actionRequest === "number") {
            // actionRequest is an id or an xmlid
            const ctx = makeContext([user.context, context]);
            delete ctx.params;

            let action = await rpc("/web/action/load", {
                action_id: actionRequest,
                context: ctx,
            });
            if (action.help) {
                action.help = markup(action.help)
            }

            return Object.assign({}, action);
        }

        // actionRequest is an object describing the action
        return actionRequest;
    };

    /**
     * 加载mobile_page的所有的action
     * 
     * @param {number} pageId 
     * @param {object} context 
     * @returns {Promise<CurrentActionInfo[]>}
     */
    async function _loadPageActions(pageId, context = {}) {
        const ctx = makeContext([user.context, context]);
        delete ctx.params;
        /** @type {CurrentActionInfo[]} */
        let actions = await rpc('/mobile_web/page_actions/load', {
            mobile_page_id: pageId,
            context: ctx
        });

        return actions;
    };

    /**
     * TODO: 加载当前view的所有action
     */
    async function loadViewActions() {
        
    };

    /**
     * 与router联动, 将当前的action转换为state, 调用router更新路由
     * 由于Mobile端没有PC端的面包屑, 所以这里的State仅保存当前的state, 也就是说actionStack始终长度为1
     * 首先使用action.path字段, 其次使用action.id字段
     *
     * @param {Action} action
     * @param {number|string|false} [resId]
     */
    function pushState(action, resId = false) {
        const stateAction = action.path ? action.path : action.id;

        /** @type {RouterState} */
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

        router.pushState(state);
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


registry.category("services").add("mobileAction", mobileActionService);

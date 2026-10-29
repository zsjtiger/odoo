import { markup } from "@odoo/owl";
import { rpc } from "@web/core/services/network/rpc";
import { user } from "@web/core/services/user";
import { makeContext } from "@web/core/data/context";

/**
 * 将 actionRequest 加载为 Action: id 或 xmlid 通过 /web/action/load 获取, 对象则原样返回
 *
 * TODO: 实现 ir.actions.client
 * TODO: 实现 web 中的 actionCache 功能(如需要)
 *
 * @param {ActionRequest} actionRequest
 * @param {Object} context
 * @returns {Promise<Action>}
 */
export async function loadAction(actionRequest, context = {}) {
    if (typeof actionRequest === "string" || typeof actionRequest === "number") {
        // actionRequest is an id or an xmlid
        const ctx = makeContext([user.context, context]);
        delete ctx.params;

        const action = await rpc("/web/action/load", {
            action_id: actionRequest,
            context: ctx,
        });
        if (action.help) {
            action.help = markup(action.help);
        }

        return Object.assign({}, action);
    }

    // actionRequest is an object describing the action
    return actionRequest;
}

/**
 * 加载 mobile_page 上的所有操作(导航栏)
 *
 * @param {number} pageId
 * @param {object} context
 * @returns {Promise<CurrentActionInfo[]>}
 */
export async function loadPageActions(pageId, context = {}) {
    const ctx = makeContext([user.context, context]);
    delete ctx.params;
    return rpc("/mobile_web/page_actions/load", {
        mobile_page_id: pageId,
        context: ctx,
    });
}

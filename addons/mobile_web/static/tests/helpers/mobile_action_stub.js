import { registry } from "@web/core/framework/registry";

/**
 * 测试用的 mobileAction 服务: 只记录 doAction 的调用, 不执行真正的动作.
 * 真实的服务在 main.js 中注册, 测试包中不会加载 main.js, 因此这里可以直接注册.
 */
export const mobileActionCalls = [];

/** 设为 error 后, 之后的 doAction 会失败 (用于测试错误处理) */
export const mobileActionState = { error: null };

registry.category("services").add("mobileAction", {
    start() {
        return {
            doAction: (actionId, options) => {
                mobileActionCalls.push({ actionId, options });
                if (mobileActionState.error) {
                    return Promise.reject(mobileActionState.error);
                }
                return Promise.resolve();
            },
        };
    },
});

/** 清空记录与错误状态, 在每个测试开始前调用 */
export function resetMobileActionCalls() {
    mobileActionCalls.length = 0;
    mobileActionState.error = null;
}

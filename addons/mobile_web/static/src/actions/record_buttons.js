import { evaluateBooleanExpr } from "@web/core/data/py_js/py";

/**
 * arch 中的 <button> 节点: 表单头部、列表与看板中的记录操作.
 * 字段内部的按钮不属于记录操作; 同名同类型的按钮只保留一个.
 *
 * @param {import("@mobile_web/views/arch").ArchNode} node
 * @returns {import("@mobile_web/views/arch").ArchNode[]}
 */
export function collectButtons(node, buttons = [], seen = new Set()) {
    for (const child of node.children) {
        if (child.tag === "button") {
            const key = `${child.attrs.type || "object"}:${child.attrs.name}`;
            if (!seen.has(key)) {
                seen.add(key);
                buttons.push(child);
            }
        } else if (child.tag !== "field") {
            collectButtons(child, buttons, seen);
        }
    }
    return buttons;
}

/**
 * 按钮的文字: arch 上的 string, 没有时使用方法名 / 动作标识
 */
export function buttonLabel(node) {
    return node.attrs.string || node.attrs.name;
}

/**
 * 按 invisible 属性判断按钮是否显示. 表达式按记录的值求值; 表达式无法求值时隐藏按钮,
 * 避免在不确定的条件下执行操作.
 *
 * @param {import("@mobile_web/views/arch").ArchNode} node
 * @param {Object} data 记录的界面值
 */
export function isButtonVisible(node, data) {
    const expr = node.attrs.invisible;
    if (!expr) {
        return true;
    }
    if (expr === "1" || expr === "True" || expr === "true") {
        return false;
    }
    try {
        return !evaluateBooleanExpr(expr, data);
    } catch {
        return false;
    }
}

/**
 * 执行一个记录按钮.
 *  - object: 调用模型方法; 方法返回的动作会被打开
 *  - action: 打开 xmlid 指定的动作, 并把当前记录作为上下文
 *
 * @returns {Promise<boolean>} 数据是否可能已经改变, 需要重新加载记录
 */
export async function runRecordButton({
    node,
    resModel,
    resIds,
    context = {},
    orm,
    mobileAction,
    confirm,
}) {
    // 需要确认的按钮: 等待用户在确认弹层中作答
    if (node.attrs.confirm && !(await confirm(node.attrs.confirm))) {
        return false;
    }
    if (node.attrs.type === "action") {
        await mobileAction.doAction(node.attrs.name, {
            additionalContext: { active_id: resIds[0], active_ids: resIds, active_model: resModel },
        });
        return false;
    }
    const result = await orm.call(resModel, node.attrs.name, [resIds], { context });
    if (result && result.type) {
        await mobileAction.doAction(result);
    }
    return true;
}

/**
 * 把按钮节点转换为弹层或头部使用的条目: 只保留可见的按钮
 *
 * @param {import("@mobile_web/views/arch").ArchNode[]} nodes
 * @param {Object} data
 * @param {(node: import("@mobile_web/views/arch").ArchNode) => () => any} makeRun
 */
export function buttonItems(nodes, data, makeRun) {
    return nodes
        .filter((node) => isButtonVisible(node, data))
        .map((node, index) => ({ key: `${index}:${node.attrs.name}`, label: buttonLabel(node), run: makeRun(node) }));
}

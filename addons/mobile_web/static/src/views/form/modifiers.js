import { evaluateModifier } from "@mobile_web/views/expression";
import { hasDisplayValue } from "@mobile_web/fields/field_utils";

/**
 * 字段 block 按当前值计算的状态 (arch 中 invisible / readonly / required 表达式)
 *
 * @param {Object} block  字段 block (见 layout.js)
 * @param {Object} values  字段名 -> 界面值
 */
export function isHiddenBlock(block, values) {
    return evaluateModifier(block.attrs?.invisible, values, false);
}

export function isReadonlyBlock(block, values) {
    return Boolean(block.readonly) || evaluateModifier(block.attrs?.readonly, values, false);
}

export function isRequiredBlock(block, values) {
    return evaluateModifier(block.attrs?.required, values, Boolean(block.field?.required));
}

/**
 * 当前必须填写却没有值的字段名 (隐藏的字段不检查, 包括 notebook 中的所有页)
 *
 * @param {Object[]} blocks
 * @param {Object} values
 * @returns {string[]}
 */
export function missingRequiredNames(blocks, values) {
    const missing = [];
    for (const block of blocks) {
        if (block.kind === "group") {
            missing.push(...missingRequiredNames(block.children, values));
        } else if (block.kind === "notebook") {
            for (const page of block.pages) {
                missing.push(...missingRequiredNames(page.blocks, values));
            }
        } else if (block.kind === "field" && !isHiddenBlock(block, values)) {
            if (isRequiredBlock(block, values) && !hasDisplayValue(values[block.name])) {
                missing.push(block.name);
            }
        }
    }
    return missing;
}

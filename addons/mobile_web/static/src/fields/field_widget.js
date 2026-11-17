import { mobileFieldRegistry } from "@mobile_web/views/registries";

/**
 * 按 arch 中的 widget 属性, 其次按字段类型, 选择移动端的字段组件.
 * 单独成文件, 便于 x2many 等组件在不引入 index.js 的情况下使用.
 *
 * @param {Object} attrs  arch 节点属性
 * @param {Object} field  字段定义
 * @returns {import("@odoo/owl").Component}
 */
export function getFieldWidget(attrs, field) {
    if (attrs.widget && mobileFieldRegistry.contains(attrs.widget)) {
        return mobileFieldRegistry.get(attrs.widget);
    }
    if (mobileFieldRegistry.contains(field.type)) {
        return mobileFieldRegistry.get(field.type);
    }
    return mobileFieldRegistry.get("fallback");
}

import "@mobile_web/fields/basic_fields";
import "@mobile_web/fields/relational_fields";
import "@mobile_web/fields/selection_fields";
import "@mobile_web/fields/numeric_fields";
import { mobileFieldRegistry } from "@mobile_web/views/registries";

/**
 * 按 arch 中的 widget 属性, 其次按字段类型, 选择移动端的字段组件
 *
 * @param {Object} attrs  arch 节点属性
 * @param {Object} field  字段定义
 * @returns {Component}
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

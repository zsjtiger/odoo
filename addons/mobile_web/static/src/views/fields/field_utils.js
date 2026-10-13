import { t } from "@odoo/owl";

/**
 * 字段组件共用的 props 与小工具
 *
 * 所有字段组件的 props:
 *  - name: 字段名
 *  - field: 字段定义(来自 loadViews)
 *  - record: MobileRecord, 当前值为 record.data[name]
 *  - readonly: 只读时只展示
 *  - attrs: arch 节点上的属性 (widget, options, placeholder ...)
 *  - onChange(value): 界面值改变时调用, 由表单视图负责触发 onchange 与保存
 *  - resModel: 记录所属模型(用于图片等需要拼接 URL 的字段)
 *  - compact: 列表/看板单元格中使用, 空值不显示占位文字
 */
export const fieldProps = {
    name: t.string(),
    field: t.object(),
    record: t.object(),
    readonly: t.boolean().optional(false),
    attrs: t.object().optional({}),
    onChange: t.function(),
    resModel: t.string().optional(""),
    // 列表与看板中的只读单元格: 空值不显示占位文字
    compact: t.boolean().optional(false),
};

/**
 * 只读展示时, 空值统一显示为 "-" 之外的空串
 */
export function displayOrEmpty(text) {
    return text === undefined || text === null || text === false ? "" : String(text);
}

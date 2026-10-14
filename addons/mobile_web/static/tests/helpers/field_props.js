import { FieldRecordAdapter } from "@mobile_web/fields/field_record";

/**
 * 与表单视图一致的记录适配层: 字段组件通过它读值、提交值.
 *
 * @param {Object} data 界面格式的值
 * @param {Object} [options]
 * @param {Object} [options.fields] 字段定义
 * @param {number|false} [options.resId] 已保存记录的 id
 * @param {Object} [options.changes] 尚未保存的改动(服务端格式)
 * @param {Function} [options.onFieldChange] 字段值写入时的回调
 */
export function recordOf(data, { fields = {}, resId = false, changes = {}, onFieldChange = () => {} } = {}) {
    return new FieldRecordAdapter({
        getRecord: () => ({ data, fields, resId, changes, isNew: !resId }),
        onFieldChange,
    });
}

/** 挂载字段组件时的公共 props */
export function fieldProps(overrides) {
    return {
        name: "value",
        field: { type: "char", string: "Value" },
        record: recordOf({}),
        readonly: false,
        attrs: {},
        onChange: () => {},
        resModel: "res.partner",
        ...overrides,
    };
}

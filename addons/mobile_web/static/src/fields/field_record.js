import { EventBus } from "@odoo/owl";

/**
 * 移动端表单的记录适配层: 实现 web 字段组件(如 useInputField)用到的 Record 接口,
 * 从而可以直接复用 web 的输入框逻辑(输入/提交/校验状态).
 *
 * 数据来自 MobileRecord; 写入时走表单的 onFieldChange, 与其他字段一样会触发 onchange.
 */
export class FieldRecordAdapter {
    /**
     * @param {Object} options
     * @param {() => import("@mobile_web/views/record").MobileRecord} options.getRecord 取当前记录
     * @param {(name: string, value: any) => Promise<void>} options.onFieldChange 字段值变化的入口
     */
    constructor({ getRecord, onFieldChange }) {
        this.getRecord = getRecord;
        this.onFieldChange = onFieldChange;
        this.model = { bus: new EventBus() };
        this.invalidFields = new Set();
    }

    get data() {
        return this.getRecord().data;
    }

    get fields() {
        return this.getRecord().fields;
    }

    get isNew() {
        return this.getRecord().isNew;
    }

    get resId() {
        return this.getRecord().resId;
    }

    /** 尚未保存的改动(服务端格式), 例如刚选择的图片 */
    get changes() {
        return this.getRecord().changes;
    }

    get isInEdition() {
        return true;
    }

    get isValid() {
        return this.invalidFields.size === 0;
    }

    isFieldInvalid(name) {
        return this.invalidFields.has(name);
    }

    setInvalidField(name) {
        this.invalidFields.add(name);
    }

    resetFieldValidity(name) {
        this.invalidFields.delete(name);
    }

    isFieldTranslatable() {
        return false;
    }

    /**
     * web 的 record.update({ name: value }, { save }) 形式, 移动端的保存由表单统一处理, 这里只转发值
     */
    async update(values) {
        for (const [name, value] of Object.entries(values)) {
            await this.onFieldChange(name, value);
        }
    }
}

/**
 * 列表/看板中的只读单元格: 字段组件仍会挂载输入框逻辑, 因此也需要适配层, 但不会写入
 *
 * @param {Object} record 列表/看板中的记录 (含 data)
 */
export function readonlyFieldRecord(record) {
    return new FieldRecordAdapter({ getRecord: () => record, onFieldChange: async () => {} });
}

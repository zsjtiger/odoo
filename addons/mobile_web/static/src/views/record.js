import { normalizeFromServer, serializeForServer } from "@mobile_web/views/record_model";

/**
 * 一条记录在界面上的状态: 当前值(data, 界面格式) 与 尚未保存的改动(changes, 服务端格式)
 */
export class MobileRecord {
    /**
     * @param {Object} fields  字段定义
     * @param {number|null} resId  null 表示新建
     * @param {Object} data  界面格式的值
     */
    constructor(fields, resId, data) {
        this.fields = fields;
        this.resId = resId;
        this.data = data;
        this.changes = {};
    }

    get isNew() {
        return !this.resId;
    }

    get isDirty() {
        return Object.keys(this.changes).length > 0;
    }

    /**
     * 更新一个字段的界面值, 并记录需要写入服务端的值
     */
    update(name, value) {
        this.data = { ...this.data, [name]: value };
        this.markChanged(name, value);
    }

    /**
     * 字段值需要写入服务端时记录下来; 服务端只读(例如计算字段)的字段不写入
     */
    markChanged(name, value) {
        const field = this.fields[name];
        if (!field || field.readonly) {
            return;
        }
        const serialized = serializeForServer(field, value);
        if (serialized !== undefined) {
            this.changes = { ...this.changes, [name]: serialized };
        }
    }

    /**
     * 只更新界面值, 不标记为已修改 (用于 onchange 返回值与默认值)
     */
    setQuiet(name, value) {
        this.data = { ...this.data, [name]: value };
    }

    /**
     * 记录的默认值需要随新建一起写入
     */
    markDefaults(names) {
        for (const name of names) {
            this.markChanged(name, this.data[name]);
        }
    }

    /**
     * 保存成功后用服务端返回的数据重置状态
     */
    reset(resId, data) {
        this.resId = resId;
        this.data = data;
        this.changes = {};
    }
}

/**
 * 服务端返回的一条记录(web 格式) -> 界面格式的 data
 *
 * @param {Object} fields
 * @param {Object} raw
 * @param {Iterable<string>} fieldNames
 * @returns {Object}
 */
export function toUIData(fields, raw, fieldNames) {
    const data = {};
    for (const name of fieldNames) {
        if (!fields[name]) {
            continue;
        }
        data[name] = normalizeFromServer(fields[name], raw[name]);
    }
    data.display_name = raw.display_name ?? false;
    return data;
}

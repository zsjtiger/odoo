const RELATIONAL_TYPES = ["many2one", "one2many", "many2many"];

/**
 * 按字段名生成服务端的 specification: 关系字段需要带上 display_name
 *
 * @param {Object} fields  字段定义(来自 loadViews)
 * @param {Iterable<string>} fieldNames
 * @returns {Object}
 */
export function buildSpec(fields, fieldNames) {
    const spec = {};
    for (const name of fieldNames) {
        const field = fields[name];
        if (!field) {
            continue;
        }
        spec[name] = RELATIONAL_TYPES.includes(field.type) ? { fields: { display_name: {} } } : {};
    }
    // 标题与关系字段的名称都依赖 display_name, 始终读取
    spec.display_name = {};
    return spec;
}

/**
 * 服务端返回的关系字段值统一为 [id, name] 或 [[id, name], ...]
 *
 * 支持的输入: false, id, [id, name], {id, display_name}, 以及它们组成的列表
 *
 * @param {Object} field
 * @param {*} value
 * @returns {*}
 */
export function normalizeFromServer(field, value) {
    if (field.type === "many2one") {
        return toPair(value);
    }
    if (field.type === "many2many" || field.type === "one2many") {
        return Array.isArray(value) ? value.map(toPair).filter(Boolean) : [];
    }
    return value;
}

function toPair(value) {
    if (value === false || value === null || value === undefined) {
        return false;
    }
    if (typeof value === "number") {
        return [value, null];
    }
    if (Array.isArray(value)) {
        return [value[0], value[1] ?? null];
    }
    if (typeof value === "object") {
        return [value.id, value.display_name ?? null];
    }
    return false;
}

/**
 * 把界面中的值转换为写入服务端时的值
 *
 * @param {Object} field
 * @param {*} value
 * @returns {*} 不需要写入时返回 undefined
 */
export function serializeForServer(field, value) {
    switch (field.type) {
        case "many2one":
            return value ? value[0] : false;
        case "many2many":
            return [[6, 0, value.map((pair) => pair[0])]];
        case "one2many":
            return undefined; // v1: one2many 只读
        default:
            return value === undefined ? false : value;
    }
}

/**
 * 与服务端交互的薄封装, 只负责调用, 不保存界面状态
 */
export class MobileRecordModel {
    /**
     * @param {Object} orm  web 的 orm 服务
     * @param {string} resModel
     * @param {Object} fields  字段定义
     * @param {Object} context
     */
    constructor(orm, resModel, fields, context = {}) {
        this.orm = orm;
        this.resModel = resModel;
        this.fields = fields;
        this.context = context;
    }

    /**
     * 分页搜索并读取记录
     *
     * @returns {Promise<{records: Object[], length: number}>}
     */
    searchRecords({ domain, fieldNames, offset = 0, limit = 40, order }) {
        return this.orm.webSearchRead(this.resModel, domain, {
            specification: buildSpec(this.fields, fieldNames),
            offset,
            limit,
            order: order || undefined,
            context: this.context,
        });
    }

    /**
     * @returns {Promise<Object|null>} 读取不到(已删除)时返回 null
     */
    async readRecord(resId, fieldNames) {
        const [record] = await this.orm.webRead(this.resModel, [resId], {
            specification: buildSpec(this.fields, fieldNames),
            context: this.context,
        });
        return record || null;
    }

    /**
     * 新建记录时的默认值
     */
    defaultGet(fieldNames) {
        return this.orm.call(this.resModel, "default_get", [fieldNames], { context: this.context });
    }

    /**
     * 保存: resId 为空时创建
     *
     * @returns {Promise<Object>} 保存后的记录(web 格式)
     */
    async saveRecord(resId, values, fieldNames) {
        const ids = resId ? [resId] : [];
        const [record] = await this.orm.webSave(this.resModel, ids, values, {
            specification: buildSpec(this.fields, fieldNames),
            context: this.context,
        });
        return record;
    }

    /**
     * 触发 onchange, 返回需要更新到界面的字段值(服务端格式)
     * triggerFields 为空时, 服务端只计算新建记录的默认值相关的字段
     *
     * @returns {Promise<{values: Object, warning?: Object}>}
     */
    async onchange(resId, changes, triggerFields, fieldNames) {
        const response = await this.orm.call(
            this.resModel,
            "onchange",
            [resId ? [resId] : [], changes, triggerFields, buildSpec(this.fields, fieldNames)],
            { context: this.context }
        );
        return { values: response.value || {}, warning: response.warning };
    }

    /**
     * 补全只有 id 的关系值的名称
     *
     * @param {string} relation
     * @param {number[]} ids
     * @returns {Promise<Object<number, string>>}
     */
    async fetchNames(relation, ids) {
        if (!ids.length) {
            return {};
        }
        const records = await this.orm.webRead(relation, ids, {
            specification: { display_name: {} },
            context: this.context,
        });
        return Object.fromEntries(records.map((r) => [r.id, r.display_name]));
    }
}

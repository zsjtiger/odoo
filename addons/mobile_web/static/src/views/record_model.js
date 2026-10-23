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
            return undefined; // 明细的改动由 lineCommands 生成命令, 见 MobileRecord.setLines
        case "binary":
            // 服务端读取时只返回 {size, checksum} 之类的信息, 没有内容: 未改动时不写回
            if (value && typeof value === "object") {
                return undefined;
            }
            return value === undefined ? false : value;
        default:
            return value === undefined ? false : value;
    }
}

/**
 * 明细(one2many)的改动转换为写入服务端的命令:
 *  - 原有明细不在当前列表中 -> [2, id] 删除
 *  - 临时 id(负数)的新明细 -> [0, 0, values] 新建
 *  - 原有明细有改动 -> [1, id, values] 更新
 *
 * @param {Object} comodelFields  明细模型的字段定义
 * @param {number[]} originalIds  保存前已有的明细 id
 * @param {Array<[number, string]>} pairs  当前明细列表
 * @param {Object<number, Object>} edits  每条明细改动过的界面值 (id -> {字段名: 界面值})
 * @returns {Array}
 */
export function lineCommands(comodelFields, originalIds, pairs, edits) {
    const current = new Set(pairs.map((pair) => pair[0]));
    const commands = originalIds.filter((id) => !current.has(id)).map((id) => [2, id]);
    for (const [id] of pairs) {
        if (id < 0) {
            commands.push([0, 0, serializeValues(comodelFields, edits[id] || {})]);
        } else if (edits[id]) {
            commands.push([1, id, serializeValues(comodelFields, edits[id])]);
        }
    }
    return commands;
}

function serializeValues(fields, values) {
    const result = {};
    for (const [name, value] of Object.entries(values)) {
        const field = fields[name];
        const serialized = field && serializeForServer(field, value);
        if (serialized !== undefined) {
            result[name] = serialized;
        }
    }
    return result;
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
    /**
     * @param {{ domain: any[], fieldNames: string[], offset?: number, limit?: number, order?: string }} options
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

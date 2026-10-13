import { Component, onWillStart, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames } from "@mobile_web/views/arch";
import { MobileRecordModel, normalizeFromServer, serializeForServer } from "@mobile_web/views/record_model";
import { MobileRecord, toUIData } from "@mobile_web/views/record";
import { buildLayout } from "@mobile_web/views/form/layout";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";

/**
 * 移动端表单视图
 *
 * - 新建: default_get + onchange 计算默认值; 保存后通过 onSaved 通知容器跳转到记录
 * - 编辑: 读取记录, 字段改动后触发 onchange, 底部固定的"放弃/保存"栏
 */
export class MobileFormView extends Component {
    static components = { FormBlocks };
    static template = xml`
        <t t-name="mobile_web.MobileFormView">
            <div class="m_form_view" t-if="this.state.record">
                <h2 class="m_form_title" t-if="this.state.record.data.display_name"><t t-esc="this.state.record.data.display_name"/></h2>
                <FormBlocks blocks="this.blocks" record="this.state.record" resModel="this.props.resModel" onFieldChange="this.onFieldChange"/>
                <div class="m_form_footer">
                    <span class="m_form_status" t-if="this.state.record.isDirty">未保存的修改</span>
                    <div class="m_form_footer_actions">
                        <button type="button" class="m_btn m_btn_secondary" t-on-click="this.onDiscard">放弃</button>
                        <button type="button" class="m_btn m_btn_primary" t-att-disabled="this.saveDisabled" t-on-click="this.onSave">
                            <t t-esc="this.state.saving ? '保存中…' : '保存'"/>
                        </button>
                    </div>
                </div>
            </div>
            <p t-elif="this.state.error" class="m_error"><t t-esc="this.state.error"/></p>
            <p t-else="" class="m_empty">加载中…</p>
        </t>
    `;
    props = useProps({
        resModel: t.string(),
        arch: t.string(),
        fields: t.object(),
        resId: t.or([t.number(), t.literal(false)]).optional(false),
        context: t.object().optional({}),
        onSaved: t.function(),
        onDiscard: t.function(),
    });
    orm = useService("orm");
    notification = useService("notification");
    state = proxy({ record: null, saving: false, error: null });

    setup() {
        const root = parseArch(this.props.arch);
        this.fieldNames = [...collectFieldNames(root)];
        this.blocks = buildLayout(root, this.props.fields);
        this.model = new MobileRecordModel(this.orm, this.props.resModel, this.props.fields, this.props.context);
        onWillStart(() => this.load());
    }

    get saveDisabled() {
        return this.state.saving || (!this.state.record.isDirty && !this.state.record.isNew);
    }

    /**
     * 读取已有记录, 或为新建记录计算默认值
     */
    async load() {
        this.state.error = null;
        try {
            if (this.props.resId) {
                const raw = await this.model.readRecord(this.props.resId, this.fieldNames);
                if (!raw) {
                    this.state.error = "记录不存在或已被删除";
                    return;
                }
                this.state.record = new MobileRecord(
                    this.props.fields,
                    this.props.resId,
                    toUIData(this.props.fields, raw, this.fieldNames)
                );
                return;
            }
            // 二进制字段的默认值是原始字节, 无法序列化为 JSON, 不请求(与 web 一致)
            const defaultNames = this.fieldNames.filter((name) => this.props.fields[name]?.type !== "binary");
            const defaults = await this.model.defaultGet(defaultNames);
            const record = new MobileRecord(this.props.fields, false, this.emptyData(defaults));
            this.state.record = record;
            // 新建时 onchange 会根据默认值计算依赖字段(例如公司带出货币)
            await this.applyOnchange([]);
            record.markDefaults(this.fieldNames);
        } catch (error) {
            this.state.error = this.errorMessage(error);
        }
    }

    /**
     * 新建记录的初始数据: 没有默认值的字段按类型给出空值
     */
    emptyData(defaults) {
        const data = {};
        for (const name of this.fieldNames) {
            const field = this.props.fields[name];
            if (!field) {
                continue;
            }
            const raw = defaults[name];
            data[name] = raw !== undefined ? normalizeFromServer(field, raw) : emptyValue(field);
        }
        data.display_name = false;
        return data;
    }

    onFieldChange = async (name, value) => {
        this.state.record.update(name, value);
        if (this.props.fields[name]) {
            await this.applyOnchange([name]);
        }
    };

    /**
     * 调用服务端 onchange, 把返回的值写回界面(并视为改动, 保存时一并提交)
     */
    async applyOnchange(triggerFields) {
        const record = this.state.record;
        try {
            const { values, warning } = await this.model.onchange(
                record.resId,
                this.serializeAll(),
                triggerFields,
                this.fieldNames
            );
            if (warning) {
                this.notification.add(warning.message, { type: "warning", title: warning.title });
            }
            for (const [name, raw] of Object.entries(values)) {
                const field = this.props.fields[name];
                if (!field || field.type === "one2many") {
                    continue;
                }
                const uiValue = await this.resolveNames(field, raw);
                record.update(name, uiValue);
            }
        } catch (error) {
            this.notification.add(this.errorMessage(error), { type: "danger" });
        }
    }

    /**
     * 当前所有字段的服务端格式值, 作为 onchange 的上下文
     */
    serializeAll() {
        const values = {};
        for (const name of this.fieldNames) {
            const field = this.props.fields[name];
            if (!field) {
                continue;
            }
            const serialized = serializeForServer(field, this.state.record.data[name]);
            if (serialized !== undefined) {
                values[name] = serialized;
            }
        }
        return values;
    }

    /**
     * onchange 返回的关系值可能只有 id, 补全名称后再放进界面
     */
    async resolveNames(field, raw) {
        if (field.type === "many2one" && typeof raw === "number") {
            const names = await this.model.fetchNames(field.relation, [raw]);
            return [raw, names[raw] ?? null];
        }
        if (field.type === "many2many" || field.type === "one2many") {
            const ids = Array.isArray(raw) && raw.length && raw.every((v) => typeof v === "number")
                ? raw
                : (Array.isArray(raw) && raw.length && Array.isArray(raw[0]) && raw[0][0] === 6 ? raw[0][2] : null);
            if (ids) {
                const names = await this.model.fetchNames(field.relation, ids);
                return ids.map((id) => [id, names[id] ?? null]);
            }
        }
        return normalizeFromServer(field, raw);
    }

    async onSave() {
        const record = this.state.record;
        if (!record.isDirty && !record.isNew) {
            return;
        }
        this.state.saving = true;
        try {
            const wasNew = record.isNew;
            const saved = await this.model.saveRecord(record.resId, { ...record.changes }, this.fieldNames);
            record.reset(saved.id, toUIData(this.props.fields, saved, this.fieldNames));
            this.notification.add("已保存", { type: "success" });
            if (wasNew) {
                this.props.onSaved(saved.id);
            }
        } catch (error) {
            this.notification.add(this.errorMessage(error), { type: "danger", sticky: true });
        } finally {
            this.state.saving = false;
        }
    }

    async onDiscard() {
        if (this.state.record.isNew) {
            return this.props.onDiscard();
        }
        await this.load();
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || "操作失败";
    }
}

/**
 * 字段类型对应的空值
 */
function emptyValue(field) {
    switch (field.type) {
        case "boolean":
            return false;
        case "many2many":
        case "one2many":
            return [];
        default:
            return false;
    }
}

mobileViewRegistry.add("form", MobileFormView);

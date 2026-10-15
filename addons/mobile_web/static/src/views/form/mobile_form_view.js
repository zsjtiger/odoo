import { Component, onWillStart, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/data/l10n/translation";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames } from "@mobile_web/views/arch";
import { MobileRecordModel, normalizeFromServer, serializeForServer } from "@mobile_web/views/record_model";
import { MobileRecord, toUIData } from "@mobile_web/views/record";
import { buildLayout } from "@mobile_web/views/form/layout";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";
import { Button } from "@mobile_web/widgets/button/button";
import { buttonItems, collectButtons, runRecordButton } from "@mobile_web/actions/record_buttons";
import { notify } from "@mobile_web/core/notification";
import { hasDisplayValue } from "@mobile_web/fields/field_utils";

/**
 * 移动端表单视图
 *
 * - 新建: default_get + onchange 计算默认值; 保存后通过 onSaved 通知容器跳转到记录
 * - 编辑: 读取记录, 字段改动后触发 onchange, 底部固定的"放弃/保存"栏
 */
// 界面文字: 用 _t 包装, 翻译由 i18n/*.po 提供(模板中通过 this.texts 引用)
const TEXTS = {
    unsaved: _t("Unsaved changes"),
    discard: _t("Discard"),
    save: _t("Save"),
    saving: _t("Saving…"),
    loading: _t("Loading…"),
    notFound: _t("The record does not exist or has been deleted"),
    saved: _t("Saved"),
    failed: _t("Operation failed"),
    saveFirst: _t("Save your changes before running this action"),
    edit: _t("Edit"),
};

export class MobileFormView extends Component {
    static components = { FormBlocks, Button };
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.MobileFormView">
            <div class="m_form_view" t-if="this.state.record">
                <h2 class="m_form_title" t-if="this.state.record.data.display_name"><t t-esc="this.state.record.data.display_name"/></h2>
                <div class="m_form_statusbar" t-if="this.headerBlocks.length">
                    <FormBlocks blocks="this.headerBlocks" record="this.fieldRecord" resModel="this.props.resModel" readonly="!this.state.editing" invalid="this.state.invalid" onFieldChange="this.onFieldChange"/>
                </div>
                <div class="m_form_header_buttons" t-if="this.headerItems.length">
                    <Button t-foreach="this.headerItems" t-as="item" t-key="item.key" label="item.label" onClick="item.run"/>
                </div>
                <FormBlocks blocks="this.blocks" record="this.fieldRecord" resModel="this.props.resModel" readonly="!this.state.editing" invalid="this.state.invalid" onFieldChange="this.onFieldChange"/>
                <div t-if="this.state.editing" class="m_form_footer">
                    <span class="m_form_status" t-if="this.state.record.isDirty"><t t-esc="this.texts.unsaved"/></span>
                    <div class="m_form_footer_actions">
                        <button type="button" class="m_btn m_btn_secondary" t-on-click="this.onDiscard"><t t-esc="this.texts.discard"/></button>
                        <button type="button" class="m_btn m_btn_primary" t-att-disabled="this.saveDisabled" t-on-click="this.onSave">
                            <t t-esc="this.state.saving ? this.texts.saving : this.texts.save"/>
                        </button>
                    </div>
                </div>
                <div t-else="" class="m_form_footer">
                    <div class="m_form_footer_actions">
                        <button type="button" class="m_btn m_btn_primary m_form_edit" t-on-click="this.onEdit"><t t-esc="this.texts.edit"/></button>
                    </div>
                </div>
            </div>
            <p t-elif="this.state.error" class="m_error"><t t-esc="this.state.error"/></p>
            <p t-else="" class="m_empty"><t t-esc="this.texts.loading"/></p>
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
    mobileAction = useService("mobileAction");
    // editing: 编辑模式 (新建记录总是编辑模式); invalid: 保存时必填但未填写的字段
    state = proxy({ record: null, saving: false, error: null, editing: false, invalid: [] });

    setup() {
        const root = parseArch(this.props.arch);
        this.fieldNames = [...collectFieldNames(root)];
        // 头部按钮: <header> 中的 <button>, 在保存后的记录上显示
        const header = root.children.find((child) => child.tag === "header");
        this.headerButtons = header ? collectButtons(header) : [];
        // 头部中的字段(如状态条), 按表单字段的方式渲染
        this.headerBlocks = header ? buildLayout(header, this.props.fields) : [];
        this.blocks = buildLayout(root, this.props.fields);
        this.model = new MobileRecordModel(this.orm, this.props.resModel, this.props.fields, this.props.context);
        // 字段组件通过适配层读写记录, 写入仍走 onFieldChange (触发 onchange)
        this.fieldRecord = new FieldRecordAdapter({
            getRecord: () => this.state.record,
            onFieldChange: (name, value) => this.onFieldChange(name, value),
        });
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
                    this.state.error = this.texts.notFound;
                    return;
                }
                this.state.record = new MobileRecord(
                    this.props.fields,
                    this.props.resId,
                    toUIData(this.props.fields, raw, this.fieldNames)
                );
                this.state.editing = false;
                this.state.invalid = [];
                return;
            }
            // 二进制字段的默认值是原始字节, 无法序列化为 JSON, 不请求(与 web 一致)
            const defaultNames = this.fieldNames.filter((name) => this.props.fields[name]?.type !== "binary");
            const defaults = await this.model.defaultGet(defaultNames);
            const record = new MobileRecord(this.props.fields, false, this.emptyData(defaults));
            this.state.record = record;
            this.state.editing = true;
            this.state.invalid = [];
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
        this.state.invalid = this.state.invalid.filter((invalidName) => invalidName !== name);
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
                notify(this.notification, warning.message, { type: "warning", title: warning.title });
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
            notify(this.notification, this.errorMessage(error), { type: "danger" });
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

    /** 进入编辑模式 */
    onEdit() {
        this.state.editing = true;
    }

    /** 视图中的必填字段没有值的名称列表 */
    missingRequired() {
        return this.fieldNames.filter((name) => this.props.fields[name]?.required && !hasDisplayValue(this.state.record.data[name]));
    }

    async onSave() {
        const record = this.state.record;
        if (!record.isDirty && !record.isNew) {
            return;
        }
        const missing = this.missingRequired();
        if (missing.length) {
            this.state.invalid = missing;
            return;
        }
        this.state.invalid = [];
        this.state.saving = true;
        try {
            const wasNew = record.isNew;
            const saved = await this.model.saveRecord(record.resId, { ...record.changes }, this.fieldNames);
            record.reset(saved.id, toUIData(this.props.fields, saved, this.fieldNames));
            this.state.editing = false;
            notify(this.notification, this.texts.saved, { type: "success" });
            if (wasNew) {
                this.props.onSaved(saved.id);
            }
        } catch (error) {
            notify(this.notification, this.errorMessage(error), { type: "danger", sticky: true });
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

    /** 头部按钮: 只对已保存的记录显示, 并按 invisible 过滤 */
    get headerItems() {
        const record = this.state.record;
        if (!record || record.isNew) {
            return [];
        }
        return buttonItems(this.headerButtons, record.data, (node) => () => this.runButton(node));
    }

    /**
     * 执行头部按钮. 有未保存的修改时先提示保存, 避免按钮基于旧数据执行
     */
    async runButton(node) {
        if (this.state.record.isDirty) {
            notify(this.notification, this.texts.saveFirst, { type: "warning" });
            return;
        }
        try {
            const reload = await runRecordButton({
                node,
                resModel: this.props.resModel,
                resIds: [this.state.record.resId],
                context: this.props.context,
                orm: this.orm,
                mobileAction: this.mobileAction,
            });
            if (reload) {
                await this.load();
            }
        } catch (error) {
            notify(this.notification, this.errorMessage(error), { type: "danger", sticky: true });
        }
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || this.texts.failed;
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

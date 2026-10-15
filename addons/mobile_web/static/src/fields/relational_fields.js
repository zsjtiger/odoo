import { Component, onWillStart, onWillUpdateProps, proxy, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty, hasDisplayValue } from "@mobile_web/fields/field_utils";
import { getFieldWidget } from "@mobile_web/fields/field_widget";
import { readonlyFieldRecord } from "@mobile_web/fields/field_record";
import { MobileRecord, toUIData } from "@mobile_web/views/record";
import { parseArch, isHiddenColumn, splitColumns } from "@mobile_web/views/arch";
import { MobileSelectSheet } from "@mobile_web/widgets/select_sheet/select_sheet";
import { LineEditor } from "@mobile_web/fields/line_editor";
import { lineCommands } from "@mobile_web/views/record_model";
import { PickerButton } from "@mobile_web/widgets/picker/picker";
import { Button } from "@mobile_web/widgets/button/button";
import { FileButton } from "@mobile_web/widgets/file_button/file_button";
import { fieldTexts } from "@mobile_web/core/texts";
import { _t } from "@web/core/data/l10n/translation";

/**
 * 关系字段的值统一为 [id, name] (many2one) 或 [[id, name], ...] (x2many)
 */
function pairName(pair) {
    return pair && (pair[1] ?? `#${pair[0]}`);
}

/**
 * 按关键字搜索关联模型, 使用服务端的 name_search
 */
function makeNameSearch(orm, relation, context) {
    return async (text) => {
        const results = await orm.call(relation, "name_search", [], {
            name: text,
            operator: "ilike",
            limit: 30,
            context,
        });
        return results.map(([id, name]) => ({ id, name }));
    };
}

// -----------------------------------------------------------------------------
// many2one
// -----------------------------------------------------------------------------

export class Many2oneField extends Component {
    texts = fieldTexts;
    static components = { MobileSelectSheet, PickerButton };
    static template = xml`
        <t t-name="mobile_web.Many2oneField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayName"/></span>
            <t t-else="">
                <PickerButton value="this.current ? this.displayName : false" placeholder="this.texts.select" onClick="this.openSheet"/>
                <MobileSelectSheet t-if="this.state.open" title="this.props.field.string"
                    search="this.search" selected="this.currentItems" allowClear="true"
                    onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false });

    setup() {
        this.search = makeNameSearch(this.orm, this.props.field.relation, {});
    }

    get current() {
        return this.props.record.data[this.props.name] || false;
    }
    get displayName() {
        return displayOrEmpty(pairName(this.current));
    }
    get currentItems() {
        return this.current ? [{ id: this.current[0], name: pairName(this.current) }] : [];
    }
    openSheet = () => {
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        const item = selected[0];
        this.props.onChange(item ? [item.id, item.name] : false);
        this.close();
    };
}
mobileFieldRegistry.add("many2one", Many2oneField);

// -----------------------------------------------------------------------------
// many2many (标签 + 多选弹层)
// -----------------------------------------------------------------------------

export class Many2manyField extends Component {
    texts = fieldTexts;
    static components = { MobileSelectSheet, Button };
    static template = xml`
        <t t-name="mobile_web.Many2manyField">
            <div class="m_tags">
                <span t-foreach="this.pairs" t-as="pair" t-key="pair[0]" class="m_tag"><t t-esc="pair[1]"/></span>
                <span t-if="!this.pairs.length and !this.props.compact" class="m_field_value m_field_empty"><t t-esc="this.texts.none"/></span>
            </div>
            <Button t-if="!this.props.readonly" label="this.texts.edit" compact="true" caret="true" onClick="this.openSheet"/>
            <MobileSelectSheet t-if="this.state.open" title="this.props.field.string" multiple="true"
                search="this.search" selected="this.currentItems"
                onConfirm="this.onConfirm" onClose="this.close"/>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false });

    setup() {
        this.search = makeNameSearch(this.orm, this.props.field.relation, {});
    }

    get pairs() {
        return (this.props.record.data[this.props.name] || []).map(([id, name]) => [id, name ?? `#${id}`]);
    }
    get currentItems() {
        return this.pairs.map(([id, name]) => ({ id, name }));
    }
    openSheet = () => {
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        this.props.onChange(selected.map((s) => [s.id, s.name]));
        this.close();
    };
}
mobileFieldRegistry.add("many2many", Many2manyField);

// -----------------------------------------------------------------------------
// many2many_checkboxes: 候选项直接以复选框列出, 适合候选项较少的场景
// -----------------------------------------------------------------------------

export class ManyToManyCheckboxesField extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.ManyToManyCheckboxesField">
            <div t-if="this.props.readonly" class="m_tags">
                <span t-foreach="this.pairs" t-as="pair" t-key="pair[0]" class="m_tag"><t t-esc="pair[1]"/></span>
                <span t-if="!this.pairs.length" class="m_field_value m_field_empty"><t t-esc="this.texts.none"/></span>
            </div>
            <ul t-else="" class="m_checkbox_list">
                <li t-foreach="this.state.options" t-as="option" t-key="option[0]">
                    <label class="m_checkbox">
                        <input type="checkbox" t-att-data-id="option[0]" t-att-checked="this.isSelected(option[0])" t-on-change="this.onToggle"/>
                        <span><t t-esc="option[1]"/></span>
                    </label>
                </li>
            </ul>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ options: [] });

    setup() {
        this.search = makeNameSearch(this.orm, this.props.field.relation, {});
        onWillStart(async () => {
            if (!this.props.readonly) {
                // 候选项与已选项合并, 已选但不在候选中的记录也要能取消选择
                const options = await this.search("");
                const selected = this.pairs.filter(([id]) => !options.some((o) => o.id === id)).map(([id, name]) => ({ id, name }));
                this.state.options = [...options, ...selected].map((o) => [o.id, o.name]);
            }
        });
    }

    get pairs() {
        return (this.props.record.data[this.props.name] || []).map(([id, name]) => [id, name ?? `#${id}`]);
    }
    isSelected(id) {
        return this.pairs.some(([pairId]) => pairId === id);
    }
    onToggle(ev) {
        const id = Number(ev.target.dataset.id);
        const option = this.state.options.find(([optionId]) => optionId === id);
        const next = ev.target.checked
            ? [...this.pairs, option]
            : this.pairs.filter(([pairId]) => pairId !== id);
        this.props.onChange(next);
    }
}
mobileFieldRegistry.add("many2many_checkboxes", ManyToManyCheckboxesField);

// -----------------------------------------------------------------------------
// one2many: 表单中展示明细(列与列表视图一致); 编辑模式下可新增, 点击行编辑, 删除.
// 改动保存为 one2many 命令 (见 lineCommands). 列表与看板单元格中只显示名称
// -----------------------------------------------------------------------------

// 新增明细的临时 id 使用负数, 保存时转换为 [0, 0, values] 命令
let tempLineId = 0;

/**
 * 明细的列表视图加载失败或尚未加载时, 仍用名称展示, 数据不会消失
 */
export class One2manyField extends Component {
    texts = fieldTexts;
    static components = { LineEditor };
    static template = xml`
        <t t-name="mobile_web.One2manyField">
            <ul t-if="this.props.compact or !this.state.rows.length" class="m_one2many_list">
                <li t-foreach="this.state.pairs" t-as="pair" t-key="pair[0]"><t t-esc="pair[1]"/></li>
                <li t-if="!this.state.pairs.length and !this.props.compact and this.props.readonly" class="m_field_empty"><t t-esc="this.texts.none"/></li>
            </ul>
            <ul t-else="" class="m_one2many_rows">
                <li t-foreach="this.state.rows" t-as="row" t-key="row.id" class="m_one2many_row"
                    t-attf-class="m_one2many_row {{ this.props.readonly ? '' : 'is_clickable' }}"
                    t-att-data-id="row.id" t-on-click="this.onRowClick">
                    <div class="m_list_primary">
                        <t t-if="row.primary" t-component="row.primary.widget" t-props="row.primary.props"/>
                    </div>
                    <div class="m_list_secondary">
                        <t t-foreach="row.secondary" t-as="cell" t-key="cell.name">
                            <span class="m_list_cell" t-if="cell.hasValue"><t t-component="cell.widget" t-props="cell.props"/></span>
                        </t>
                    </div>
                </li>
            </ul>
            <button t-if="!this.props.readonly and this.state.schemaReady" type="button" class="m_one2many_add" t-on-click="this.addLine">
                <t t-esc="this.texts.addLine"/>
            </button>
            <p t-if="!this.props.readonly and !this.state.schemaReady" class="m_field_hint"><t t-esc="this.texts.loading"/></p>
            <LineEditor t-if="this.state.editing"
                title="this.state.editing.title"
                resModel="this.props.field.relation"
                blocks="this.state.editing.blocks"
                record="this.state.editing.record"
                fields="this.schema.fields"
                onSave="this.saveLine"
                onCancel="this.cancelLine"
                onDelete="this.state.editing.isNew ? null : this.deleteLine"/>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    view = useService("view");
    state = proxy({ pairs: [], rows: [], lines: {}, edits: {}, schemaReady: false, editing: null });
    schema = null;
    loadedKey = null;
    lastPairs = null;

    setup() {
        // 编辑页通过 props 回调, 需要绑定 this
        this.saveLine = this.saveLine.bind(this);
        this.cancelLine = this.cancelLine.bind(this);
        this.deleteLine = this.deleteLine.bind(this);
        this.syncFromRecord();
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            // 记录被重新读取(保存后或放弃改动)时, 以记录中的值为准
            if (nextProps.record.data[nextProps.name] !== this.lastPairs) {
                this.syncFromRecord(nextProps);
            }
            return this.load(nextProps);
        });
    }

    get recordFields() {
        return this.schema?.fields || {};
    }

    syncFromRecord(props = this.props) {
        const pairs = (props.record.data[props.name] || []).map(([id, name]) => [id, name ?? `#${id}`]);
        this.lastPairs = props.record.data[props.name];
        this.state.pairs = pairs;
        this.state.edits = { ...(props.record.getRecord().lineEdits?.[props.name] || {}) };
        this.loadedKey = null;
        this.state.lines = {};
        this.refreshRows();
    }

    /**
     * 读取明细的列表视图(字段与列), 以及明细的记录 (只在需要时读取)
     */
    async load(props = this.props) {
        const relation = props.field.relation;
        const ids = this.state.pairs.map(([id]) => id).filter((id) => id > 0);
        const key = `${relation}:${ids.join(",")}`;
        if (props.compact || !relation) {
            this.state.rows = [];
            return;
        }
        try {
            await this.ensureSchema(relation);
            if (this.loadedKey === key || !ids.length) {
                this.loadedKey = key;
                this.refreshRows();
                return;
            }
            const missing = ids.filter((id) => !this.state.lines[id]);
            if (missing.length) {
                const raws = await this.orm.read(relation, missing, this.schema.readNames);
                for (const raw of raws) {
                    this.state.lines[raw.id] = toUIData(this.schema.fields, raw, this.schema.readNames);
                }
            }
            this.loadedKey = key;
            this.refreshRows();
        } catch {
            // 加载失败时保留名称展示
            this.state.rows = [];
        }
    }

    async ensureSchema(relation) {
        if (this.schema && this.schema.relation === relation) {
            return;
        }
        const { fields, views } = await this.view.loadViews({
            resModel: relation,
            views: [[false, "list"]],
            context: {},
        });
        const node = parseArch(views.list.arch);
        const allColumns = node.children
            .filter((c) => c.tag === "field" && c.attrs.name && fields[c.attrs.name])
            .map((c) => ({ name: c.attrs.name, attrs: c.attrs, field: fields[c.attrs.name] }));
        const columns = allColumns.filter((c) => !isHiddenColumn({ tag: "field", attrs: c.attrs, children: [] }));
        const { primary, secondary } = splitColumns(columns);
        // 读取全部列(包括隐藏列, 例如金额的币种), 与表单中的字段
        const readNames = [...new Set(allColumns.flatMap((c) => [c.name, c.field.currency_field].filter((n) => n && fields[n])))];
        const editorBlocks = columns.map((column, index) => ({
            kind: "field",
            key: `line.${index}`,
            name: column.name,
            attrs: column.attrs,
            field: column.field,
            label: column.attrs.string || column.field.string,
            stacked: ["text", "html", "binary"].includes(column.field.type),
            required: Boolean(column.field.required),
            hideLabel: false,
            widget: getFieldWidget(column.attrs, column.field),
            readonly: Boolean(column.field.readonly),
        }));
        this.schema = { relation, fields, columns, primary, secondary, readNames, editorBlocks };
        this.state.schemaReady = true;
    }

    /** 每条明细的界面值: 读取的值加上界面上的改动 */
    lineData(id) {
        return { ...(this.state.lines[id] || {}), ...(this.state.edits[id] || {}) };
    }

    /** 明细的显示名称: 第一列的值, 没有时使用默认名称 */
    labelOf(id) {
        const primary = this.schema?.primary;
        const data = this.lineData(id);
        const value = primary ? data[primary.name] : undefined;
        if (Array.isArray(value)) {
            return value[1] ?? `#${value[0]}`;
        }
        if (value !== undefined && value !== false && value !== "") {
            return String(value);
        }
        return id < 0 ? this.texts.newLine : `#${id}`;
    }

    /** 由当前明细列表生成界面行 (带有单元格的组件与值) */
    refreshRows() {
        if (!this.schema || !this.state.pairs.length || this.props.compact) {
            this.state.rows = [];
            return;
        }
        const { fields, primary, secondary, relation } = this.schema;
        this.state.rows = this.state.pairs
            .filter(([id]) => id < 0 || this.state.lines[id])
            .map(([id]) => {
                const record = new MobileRecord(fields, id, this.lineData(id));
                return {
                    id,
                    primary: primary && this.cell(primary, record, relation),
                    secondary: secondary.map((column) => this.cell(column, record, relation)),
                };
            });
    }

    cell(column, record, relation) {
        return {
            name: column.name,
            widget: getFieldWidget(column.attrs, column.field),
            hasValue: hasDisplayValue(record.data[column.name]),
            props: {
                name: column.name,
                field: column.field,
                record: readonlyFieldRecord(record),
                readonly: true,
                attrs: column.attrs,
                resModel: relation,
                compact: true,
                onChange: () => {},
            },
        };
    }

    /** 把明细列表与改动写回表单记录 (保存时生成 one2many 命令) */
    commit(pairs, edits) {
        this.state.pairs = pairs;
        this.state.edits = edits;
        this.refreshRows();
        const originalIds = (this.props.record.getRecord().original[this.props.name] || []).map((pair) => pair[0]);
        const commands = lineCommands(this.recordFields, originalIds, pairs, edits);
        const data = pairs.map(([id]) => [id, this.labelOf(id)]);
        this.lastPairs = data;
        this.props.record.getRecord().setLines(this.props.name, data, edits, commands);
    }

    onRowClick(ev) {
        if (this.props.readonly) {
            return;
        }
        this.openLine(Number(ev.currentTarget.dataset.id));
    }

    openLine(id) {
        const data = this.lineData(id);
        this.state.editing = {
            id,
            isNew: id < 0 && !this.state.lines[id],
            title: this.texts.editLine,
            blocks: this.schema.editorBlocks,
            record: new MobileRecord(this.schema.fields, id, data),
        };
    }

    addLine() {
        tempLineId += 1;
        const id = -tempLineId;
        this.commit([...this.state.pairs, [id, this.texts.newLine]], this.state.edits);
        this.openLine(id);
    }

    saveLine(changedNames, data) {
        const { id } = this.state.editing;
        const edits = { ...this.state.edits };
        const picked = {};
        for (const name of changedNames) {
            picked[name] = data[name];
        }
        edits[id] = { ...(edits[id] || {}), ...picked };
        const pairs = this.state.pairs.some(([pairId]) => pairId === id)
            ? this.state.pairs
            : [...this.state.pairs, [id, this.texts.newLine]];
        this.state.editing = null;
        this.commit(pairs, edits);
    }

    cancelLine() {
        const { id, isNew } = this.state.editing;
        this.state.editing = null;
        if (isNew) {
            // 新增的明细取消时直接移除
            const edits = { ...this.state.edits };
            delete edits[id];
            this.commit(this.state.pairs.filter(([pairId]) => pairId !== id), edits);
        }
    }

    deleteLine() {
        const { id } = this.state.editing;
        this.state.editing = null;
        const edits = { ...this.state.edits };
        delete edits[id];
        this.commit(this.state.pairs.filter(([pairId]) => pairId !== id), edits);
    }
}
mobileFieldRegistry.add("one2many", One2manyField);

// -----------------------------------------------------------------------------
// binary / image (拍照或从相册选择)
// -----------------------------------------------------------------------------

export class BinaryField extends Component {
    texts = fieldTexts;
    static components = { Button, FileButton };
    static template = xml`
        <t t-name="mobile_web.BinaryField">
            <t t-if="this.props.readonly">
                <img t-if="this.imageSrc" class="m_field_image" t-att-src="this.imageSrc" alt=""/>
                <span t-elif="!this.props.compact" class="m_field_value m_field_empty"><t t-esc="this.texts.none"/></span>
            </t>
            <div t-else="" class="m_binary">
                <img t-if="this.imageSrc" class="m_field_image" t-att-src="this.imageSrc" alt=""/>
                <div class="m_binary_actions">
                    <FileButton label="this.hasValue ? this.texts.changeImage : this.texts.selectImage" capture="environment" onFile="this.onFileData"/>
                    <Button t-if="this.hasValue" label="this.texts.delete" compact="true" danger="true" onClick="this.onClear"/>
                </div>
            </div>
        </t>
    `;
    props = useProps(fieldProps);

    get hasValue() {
        return !!this.props.record.data[this.props.name];
    }
    get imageSrc() {
        const value = this.props.record.data[this.props.name];
        if (!value) {
            return null;
        }
        // 刚选择(未保存)的图片是 base64, 已保存的通过 /web/image 读取
        if (this.props.record.changes[this.props.name] !== undefined) {
            return `data:image/*;base64,${value}`;
        }
        return `/web/image/${this.props.resModel}/${this.props.record.resId}/${this.props.name}`;
    }
    /** 选中的图片内容(base64), 由文件按钮回传 */
    onFileData = (base64) => {
        this.props.onChange(base64);
    };
    onClear = () => {
        this.props.onChange(false);
    };
}
mobileFieldRegistry.add("binary", BinaryField);
mobileFieldRegistry.add("image", BinaryField);

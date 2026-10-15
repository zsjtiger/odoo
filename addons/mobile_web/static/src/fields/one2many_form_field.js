import { proxy, useProps, xml } from "@odoo/owl";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { One2manyField } from "@mobile_web/fields/relational_fields";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";
import { buildLayout } from "@mobile_web/views/form/layout";
import { missingRequiredNames } from "@mobile_web/views/form/modifiers";
import { parseArch } from "@mobile_web/views/arch";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";
import { MobileRecord } from "@mobile_web/views/record";
import { fieldProps } from "@mobile_web/fields/field_utils";

// 新增明细的临时 id 使用负数(与 one2many 一致, 保存时转换为 [0, 0, values] 命令)
let tempLineId = 0;

/** 表单布局中出现的全部字段名(含分组与分页中的字段) */
function collectNames(blocks) {
    return blocks.flatMap((block) => {
        if (block.kind === "field") {
            return [block.name];
        }
        if (block.kind === "group") {
            return collectNames(block.children);
        }
        if (block.kind === "notebook") {
            return block.pages.flatMap((page) => collectNames(page.blocks));
        }
        return [];
    });
}

/**
 * 内嵌明细表单 (一对多, widget="one2many_form"): 每条明细是一张卡片, 卡片中就是 M 模型表单视图的字段,
 * 可以直接编辑; "添加" 一次追加一张空卡片, 卡片右上角的 × 删除该条明细.
 * 明细与一对多的其他部件一样保存为 one2many 命令. 必填字段未填写时, 保存表单会被拦截.
 *
 * 与一对多的区别: 明细的字段来自关联模型的表单视图(而不是列表视图), 编辑不进入单独的编辑页.
 */
export class One2manyFormField extends One2manyField {
    static components = { FormBlocks };
    static template = xml`
        <t t-name="mobile_web.One2manyFormField">
            <div class="m_o2m_head">
                <span class="m_o2m_title"><t t-esc="this.props.field.string"/></span>
                <button t-if="!this.props.readonly and this.state.schemaReady" type="button" class="m_o2m_add" t-on-click="this.addLine">
                    <t t-esc="this.texts.addLine"/>
                </button>
            </div>
            <p t-if="!this.state.schemaReady and this.state.pairs.length" class="m_field_hint"><t t-esc="this.texts.loading"/></p>
            <p t-if="this.state.schemaReady and !this.state.cards.length and this.props.readonly" class="m_field_empty"><t t-esc="this.texts.none"/></p>
            <div t-foreach="this.state.cards" t-as="card" t-key="card.id" class="m_o2m_card" t-att-data-id="card.id">
                <button t-if="!this.props.readonly" type="button" class="m_o2m_card_delete" t-att-data-id="card.id"
                        t-att-aria-label="this.texts.deleteLine" t-on-click="this.onRemoveClick">×</button>
                <div t-attf-class="m_form_view m_o2m_body {{ this.props.readonly ? 'is_readonly' : '' }}">
                    <FormBlocks blocks="this.schema.editorBlocks" record="card.record" resModel="this.props.field.relation"
                                readonly="this.props.readonly" invalid="card.invalid" onFieldChange="card.onChange"/>
                </div>
            </div>
        </t>
    `;
    props = useProps(fieldProps);
    state = proxy({ pairs: [], rows: [], cards: [], lines: {}, edits: {}, schemaReady: false, editing: null });

    setup() {
        super.setup();
        // 字段组件的校验在表单保存时调用, 每次刷新明细时重新注册
        this.registerValidator();
    }

    /** 读取关联模型的表单视图: 字段布局与表单一致 */
    async ensureSchema(relation) {
        if (this.schema && this.schema.relation === relation) {
            return;
        }
        const { fields, views } = await this.view.loadViews({
            resModel: relation,
            views: [[false, "form"]],
            context: {},
        });
        const blocks = buildLayout(parseArch(views.form.arch), fields);
        const names = collectNames(blocks);
        const readNames = [...new Set(names.flatMap((n) => [n, fields[n]?.currency_field].filter((x) => x && fields[x])))];
        // 明细的显示名称取表单中的第一个字段
        const primaryName = names.find((n) => fields[n]);
        this.schema = {
            relation,
            fields,
            readNames,
            primary: primaryName ? { name: primaryName } : null,
            editorBlocks: blocks,
        };
        this.state.schemaReady = true;
    }

    /** 每条明细一张卡片: 字段值来自明细的界面值(读取的值 + 界面改动) */
    refreshRows() {
        if (!this.schema || !this.state.pairs.length || this.props.compact) {
            this.state.cards = [];
            this.registerValidator();
            return;
        }
        this.state.cards = this.state.pairs
            .filter(([id]) => id < 0 || this.state.lines[id])
            .map(([id]) => {
                const record = new MobileRecord(this.schema.fields, id, this.lineData(id));
                return {
                    id,
                    record: new FieldRecordAdapter({
                        getRecord: () => record,
                        onFieldChange: async (name, value) => this.onLineChange(id, name, value),
                    }),
                    invalid: [],
                    onChange: (name, value) => this.onLineChange(id, name, value),
                };
            });
        this.registerValidator();
    }

    /** 没有必填字段未填写的明细才通过校验 (只检查已读取的明细) */
    linesValid() {
        if (!this.schema) {
            return true;
        }
        return this.state.pairs
            .filter(([id]) => id < 0 || this.state.lines[id])
            .every(([id]) => missingRequiredNames(this.schema.editorBlocks, this.lineData(id)).length === 0);
    }

    registerValidator() {
        const rec = this.props.record?.getRecord?.();
        if (rec && rec.validators) {
            rec.validators[this.props.name] = () => this.linesValid();
        }
    }

    onLineChange(id, name, value) {
        const edits = { ...this.state.edits, [id]: { ...(this.state.edits[id] || {}), [name]: value } };
        this.commit(this.state.pairs, edits);
    }

    /** 添加一条空明细(直接显示为卡片, 不打开编辑页) */
    addLine() {
        tempLineId += 1;
        const id = -tempLineId;
        this.commit([...this.state.pairs, [id, this.texts.newLine]], this.state.edits);
    }

    onRemoveClick = (ev) => {
        this.removeLine(Number(ev.currentTarget.dataset.id));
    };

    removeLine(id) {
        const edits = { ...this.state.edits };
        delete edits[id];
        this.commit(this.state.pairs.filter(([pairId]) => pairId !== id), edits);
    }
}
mobileFieldRegistry.add("one2many_form", One2manyFormField);

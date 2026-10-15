import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { FormBlocks } from "@mobile_web/views/form/form_blocks";
import { FieldRecordAdapter } from "@mobile_web/fields/field_record";
import { missingRequiredNames } from "@mobile_web/views/form/modifiers";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 明细行的编辑页: 全屏展示明细模型的字段(与明细列表的列一致), 保存后交回 one2many 字段
 *
 * props.blocks: 展示用的 block 列表 (kind: "field")
 * props.record: 该行的 MobileRecord
 */
export class LineEditor extends Component {
    static template = xml`
        <t t-name="mobile_web.LineEditor">
            <div class="m_line_editor">
                <div class="m_line_editor_head">
                    <button type="button" class="m_line_editor_cancel" t-on-click="this.props.onCancel"><t t-esc="this.texts.cancel"/></button>
                    <span class="m_line_editor_title"><t t-esc="this.props.title"/></span>
                    <button type="button" class="m_btn m_btn_primary m_line_editor_save" t-on-click="this.onSave"><t t-esc="this.texts.save"/></button>
                </div>
                <div class="m_line_editor_body m_form_view">
                    <FormBlocks blocks="this.props.blocks" record="this.adapter" resModel="this.props.resModel" readonly="false" invalid="this.state.invalid" onFieldChange="this.onFieldChange"/>
                </div>
                <div t-if="this.props.onDelete" class="m_line_editor_foot">
                    <button type="button" class="m_btn m_btn_secondary m_line_editor_delete" t-on-click="this.props.onDelete"><t t-esc="this.texts.deleteLine"/></button>
                </div>
            </div>
        </t>
    `;
    static components = { FormBlocks };
    props = useProps({
        title: t.string(),
        resModel: t.string().optional(""),
        blocks: t.array(),
        record: t.object(),
        fields: t.object(),
        onSave: t.function(),
        onCancel: t.function(),
        onDelete: t.function().optional(null),
    });
    texts = fieldTexts;
    state = proxy({ record: this.props.record, changed: [], invalid: [] });
    adapter = new FieldRecordAdapter({
        getRecord: () => this.state.record,
        onFieldChange: async (name, value) => this.onFieldChange(name, value),
    });

    onFieldChange = (name, value) => {
        this.state.record.update(name, value);
        if (!this.state.changed.includes(name)) {
            this.state.changed = [...this.state.changed, name];
        }
        this.state.invalid = this.state.invalid.filter((invalidName) => invalidName !== name);
    };

    onSave() {
        const missing = missingRequiredNames(this.props.blocks, this.state.record.data);
        if (missing.length) {
            this.state.invalid = missing;
            return;
        }
        this.props.onSave(this.state.changed, this.state.record.data);
    }

}

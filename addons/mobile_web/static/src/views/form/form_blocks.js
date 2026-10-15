import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";

const TEXTS = {
    required: _t("This field is required"),
};

/**
 * 递归渲染 form 的 block 树(group / field / notebook / separator)
 */
export class FormBlocks extends Component {
    static template = xml`
        <t t-name="mobile_web.FormBlocks">
            <t t-foreach="this.props.blocks" t-as="block" t-key="block.key">
                <section t-if="block.kind === 'group'" class="m_form_group">
                    <h3 t-if="block.title" class="m_form_separator"><t t-esc="block.title"/></h3>
                    <FormBlocks blocks="block.children" record="this.props.record" resModel="this.props.resModel" readonly="this.props.readonly" invalid="this.props.invalid" onFieldChange="this.props.onFieldChange"/>
                </section>
                <div t-elif="block.kind === 'field'" t-attf-class="m_form_field {{ block.stacked ? 'is_stacked' : '' }} {{ this.isInvalid(block) ? 'is_invalid' : '' }}">
                    <label t-if="!block.hideLabel" class="m_form_label"><t t-esc="block.label"/><span t-if="block.required and !this.props.readonly" class="m_form_required">*</span></label>
                    <div class="m_form_value">
                        <t t-component="block.widget" t-props="this.fieldProps(block)"/>
                        <p t-if="this.isInvalid(block)" class="m_form_error"><t t-esc="this.texts.required"/></p>
                    </div>
                </div>
                <h3 t-elif="block.kind === 'separator'" class="m_form_separator"><t t-esc="block.text"/></h3>
                <div t-elif="block.kind === 'notebook'" class="m_form_notebook">
                    <div class="m_form_tabs" role="tablist">
                        <button t-foreach="block.pages" t-as="page" t-key="page_index" type="button" role="tab"
                                t-attf-class="m_segmented_item {{ this.activeTab(block) === page_index ? 'is_active' : '' }}"
                                t-att-data-notebook="block.key" t-att-data-page="page_index" t-on-click="this.onTabClick">
                            <t t-esc="page.title"/>
                        </button>
                    </div>
                    <FormBlocks t-if="this.activePage(block)" blocks="this.activePage(block).blocks" record="this.props.record"
                                resModel="this.props.resModel" readonly="this.props.readonly" invalid="this.props.invalid" onFieldChange="this.props.onFieldChange"/>
                </div>
            </t>
        </t>
    `;
    texts = TEXTS;
    props = useProps({
        blocks: t.array(),
        record: t.object(),
        resModel: t.string().optional(""),
        readonly: t.boolean().optional(false),
        invalid: t.array().optional([]),
        onFieldChange: t.function(),
    });
    state = proxy({ tabs: {} });

    fieldProps(block) {
        return {
            name: block.name,
            field: block.field,
            record: this.props.record,
            readonly: this.props.readonly || block.readonly,
            attrs: block.attrs,
            resModel: this.props.resModel,
            onChange: (value) => this.props.onFieldChange(block.name, value),
        };
    }

    /** 必填字段没有填写时, 保存前标记为无效 */
    isInvalid(block) {
        return this.props.invalid.includes(block.name);
    }

    activeTab(block) {
        return this.state.tabs[block.key] || 0;
    }

    activePage(block) {
        return block.pages[this.activeTab(block)];
    }

    onTabClick(ev) {
        const { notebook, page } = ev.currentTarget.dataset;
        this.state.tabs[notebook] = Number(page);
    }
}
FormBlocks.components = { FormBlocks };

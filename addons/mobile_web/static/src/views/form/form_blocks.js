import { Component, proxy, t, useProps, xml } from "@odoo/owl";

/**
 * 递归渲染 form 的 block 树(group / field / notebook / separator)
 */
export class FormBlocks extends Component {
    static template = xml`
        <t t-name="mobile_web.FormBlocks">
            <t t-foreach="this.props.blocks" t-as="block" t-key="block.key">
                <section t-if="block.kind === 'group'" class="m_form_group">
                    <h3 t-if="block.title" class="m_form_separator"><t t-esc="block.title"/></h3>
                    <FormBlocks blocks="block.children" record="this.props.record" resModel="this.props.resModel" onFieldChange="this.props.onFieldChange"/>
                </section>
                <div t-elif="block.kind === 'field'" t-attf-class="m_form_field {{ block.stacked ? 'is_stacked' : '' }}">
                    <label class="m_form_label"><t t-esc="block.label"/></label>
                    <div class="m_form_value">
                        <t t-component="block.widget" t-props="this.fieldProps(block)"/>
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
                                resModel="this.props.resModel" onFieldChange="this.props.onFieldChange"/>
                </div>
            </t>
        </t>
    `;
    props = useProps({
        blocks: t.array(),
        record: t.object(),
        resModel: t.string().optional(""),
        onFieldChange: t.function(),
    });
    state = proxy({ tabs: {} });

    fieldProps(block) {
        return {
            name: block.name,
            field: block.field,
            record: this.props.record,
            readonly: block.readonly,
            attrs: block.attrs,
            resModel: this.props.resModel,
            onChange: (value) => this.props.onFieldChange(block.name, value),
        };
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

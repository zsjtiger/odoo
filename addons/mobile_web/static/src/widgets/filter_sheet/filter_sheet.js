import { Component, proxy, t, useProps, xml } from "@odoo/owl";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 自定义筛选面板: 按模型的 dynamic_filter_config 展示分组, 每组可以有选项 (按钮或单选) 与卡片 (多对一记录).
 *
 * props.sections: [{ name, label, options: [{key, label, radio}], cards: null | {field, records: [{id, name, sub}]} }]
 * props.selected: { options: string[], cards: Object<string, number[]> }
 */
export class MobileFilterSheet extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.MobileFilterSheet">
            <div class="m_sheet_backdrop" t-on-click="this.props.onClose">
                <div class="m_sheet m_filter_sheet" role="dialog" t-on-click="this.stop">
                    <header class="m_sheet_header">
                        <button type="button" class="m_sheet_btn" t-on-click="this.props.onClose"><t t-esc="this.texts.cancel"/></button>
                        <span class="m_sheet_title"><t t-esc="this.props.title"/></span>
                        <button type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
                    </header>
                    <div class="m_filter_body">
                        <section t-foreach="this.props.sections" t-as="section" t-key="section.name" class="m_filter_section">
                            <h4 t-if="section.label" class="m_filter_title"><t t-esc="section.label"/></h4>
                            <div class="m_filter_options">
                                <button t-foreach="section.options" t-as="option" t-key="option.key" type="button"
                                        t-attf-class="{{ option.radio ? 'm_filter_radio' : 'm_filter_chip' }} {{ this.isOn(option.key) ? 'is_on' : '' }}"
                                        t-att-data-key="option.key" t-on-click="this.toggleOption">
                                    <span t-if="option.radio" class="m_filter_radio_dot"/>
                                    <t t-esc="option.label"/>
                                </button>
                            </div>
                            <div t-if="section.cards and section.cards.records.length" class="m_filter_cards">
                                <button t-foreach="section.cards.records" t-as="record" t-key="record.id" type="button"
                                        t-attf-class="m_filter_card {{ this.isCardOn(section.cards.field, record.id) ? 'is_on' : '' }}"
                                        t-att-data-field="section.cards.field" t-att-data-id="record.id" t-on-click="this.toggleCard">
                                    <span class="m_filter_card_name"><t t-esc="record.name"/></span>
                                    <span t-if="record.sub" class="m_filter_card_sub"><t t-esc="record.sub"/></span>
                                </button>
                            </div>
                        </section>
                    </div>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        title: t.string(),
        sections: t.array(),
        selected: t.object(),
        onConfirm: t.function(),
        onClose: t.function(),
    });
    state = proxy({
        options: [...(this.props.selected.options || [])],
        cards: Object.fromEntries(Object.entries(this.props.selected.cards || {}).map(([k, v]) => [k, [...v]])),
    });

    stop(ev) {
        ev.stopPropagation();
    }

    isOn(key) {
        return this.state.options.includes(key);
    }

    isCardOn(field, id) {
        return (this.state.cards[field] || []).includes(id);
    }

    toggleOption(ev) {
        const key = ev.currentTarget.dataset.key;
        this.state.options = this.isOn(key)
            ? this.state.options.filter((k) => k !== key)
            : [...this.state.options, key];
    }

    toggleCard(ev) {
        const field = ev.currentTarget.dataset.field;
        const id = Number(ev.currentTarget.dataset.id);
        const current = this.state.cards[field] || [];
        this.state.cards = {
            ...this.state.cards,
            [field]: current.includes(id) ? current.filter((v) => v !== id) : [...current, id],
        };
    }

    onConfirm() {
        this.props.onConfirm({ options: [...this.state.options], cards: { ...this.state.cards } });
    }
}

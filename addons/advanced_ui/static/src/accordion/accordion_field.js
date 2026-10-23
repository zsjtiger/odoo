import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { Field } from "@web/views/fields/field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Accordion } from "./accordion";

/**
 * Accordion field widget for One2many fields. Each line of the relation is a row:
 * its summary is the value of the "summary" option, and the open row shows the
 * fields of the inline <list> of the field, laid out like a form group.
 *
 * <field name="line_ids" widget="accordion" options="{'summary': 'name'}">
 *     <list><field name="name"/><field name="qty"/></list>
 * </field>
 */
export class AccordionField extends Component {
    static template = "advanced_ui.AccordionField";
    static components = { Accordion, Field };
    props = useProps({
        ...standardFieldProps,
        summaryField: t.string().optional(),
        views: t.object().optional(),
    });

    get items() {
        return this.props.record.data[this.props.name].records.map((row) => ({
            id: row.id,
            summary: this.props.summaryField ? row.data[this.props.summaryField] : row.data.display_name,
            row,
        }));
    }

    /** Fields of the inline list, except the summary field, as field infos for a form. */
    get detailFields() {
        const view = this.props.views?.list || this.props.views?.default || {};
        return Object.values(view.fieldNodes || {}).filter(
            (fieldInfo) => fieldInfo.name !== this.props.summaryField
        );
    }

    getFieldInfo(fieldInfo) {
        return { ...fieldInfo, viewType: "form" };
    }
}

registry.category("fields").add("accordion", {
    component: AccordionField,
    displayName: _t("Accordion"),
    supportedTypes: ["one2many"],
    supportedOptions: [
        {
            label: _t("Summary field"),
            name: "summary",
            type: "field",
            availableTypes: ["char"],
        },
    ],
    useSubView: true,
    extractProps: ({ options, views }) => ({ summaryField: options.summary, views }),
});

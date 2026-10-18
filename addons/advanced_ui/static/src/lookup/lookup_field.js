import { t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { Many2One, many2OneProps } from "@web/views/fields/relational/many2one/many2one";
import {
    Many2OneField,
    extractM2OFieldProps,
    many2OneFieldProps,
    buildM2OFieldDescription,
    m2oSupportedOptions,
} from "@web/views/fields/relational/many2one/many2one_field";
import { LookupAutocomplete } from "./lookup_autocomplete";

class LookupMany2One extends Many2One {
    static components = { Many2XAutocomplete: LookupAutocomplete };
    props = useProps({ ...many2OneProps, lookupFields: t.object().optional() });

    get many2XAutocompleteProps() {
        return { ...super.many2XAutocompleteProps, lookupFields: this.props.lookupFields };
    }
}

/**
 * Many2one field with the lookup dropdown. The "subtitle" option names a field of the
 * related model shown under each name, and the "group" option names a field whose
 * values head the groups of suggestions.
 */
export class LookupMany2OneField extends Many2OneField {
    static components = { Many2One: LookupMany2One };
    props = useProps({ ...many2OneFieldProps, lookupFields: t.object().optional() });

    get m2oProps() {
        const { subtitle, group } = this.props.lookupFields || {};
        const specification = Object.fromEntries(
            [subtitle, group].filter(Boolean).map((fieldName) => [fieldName, {}])
        );
        return { ...super.m2oProps, lookupFields: this.props.lookupFields, specification };
    }
}

registry.category("fields").add("lookup", {
    ...buildM2OFieldDescription(LookupMany2OneField),
    displayName: _t("Lookup"),
    supportedOptions: [
        ...m2oSupportedOptions,
        {
            label: _t("Subtitle field"),
            name: "subtitle",
            type: "field",
            availableTypes: ["char"],
        },
        {
            label: _t("Group field"),
            name: "group",
            type: "field",
            availableTypes: ["char"],
        },
    ],
    extractProps(staticInfo, dynamicInfo) {
        const { subtitle, group } = staticInfo.options;
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            lookupFields: { subtitle, group },
        };
    },
});

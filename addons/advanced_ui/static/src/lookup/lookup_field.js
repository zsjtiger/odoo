import { t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { Many2One } from "@web/views/fields/relational/many2one/many2one";
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
}

/**
 * Many2one field with the lookup dropdown. The "subtitle" option names a field of the
 * related model, read for each suggestion and shown under its name.
 */
export class LookupMany2OneField extends Many2OneField {
    static components = { Many2One: LookupMany2One };
    props = useProps({ ...many2OneFieldProps, subtitle: t.string().optional() });

    get m2oProps() {
        return {
            ...super.m2oProps,
            specification: this.props.subtitle ? { [this.props.subtitle]: {} } : undefined,
        };
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
    ],
    extractProps(staticInfo, dynamicInfo) {
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            subtitle: staticInfo.options.subtitle,
        };
    },
});

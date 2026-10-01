import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { booleanField, BooleanField } from "../boolean/boolean_field";

export class BooleanToggleField extends BooleanField {
    async onChange(newValue) {
        this.state.value = newValue;
        const changes = { [this.props.name]: newValue };
        await this.props.record.update(changes);
    }

    get displayAsToggle() {
        return true;
    }
}

export const booleanToggleField = {
    ...booleanField,
    component: BooleanToggleField,
    displayName: _t("Toggle"),
    additionalClasses: ["o_boolean_interactive"],
    extractProps(_, dynamicInfo) {
        return {
            readonly: dynamicInfo.readonly,
        };
    },
};

registry.category("fields").add("boolean_toggle", booleanToggleField);

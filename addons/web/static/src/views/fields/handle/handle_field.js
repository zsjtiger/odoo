import { registry } from "@web/core/framework/registry";
import { _t } from "@web/core/data/l10n/translation";
import { standardFieldProps } from "../standard_field_props";

import { Component, useProps } from "@odoo/owl";

export class HandleField extends Component {
    static template = "web.HandleField";
    props = useProps({
        ...standardFieldProps,
    });
}

export const handleField = {
    component: HandleField,
    displayName: _t("Handle"),
    supportedTypes: ["integer"],
    isEmpty: () => false,
    listViewWidth: 20,
    extractProps(_, dynamicInfo) {
        return {
            readonly: dynamicInfo.readonly,
        };
    },
};

registry.category("fields").add("handle", handleField);

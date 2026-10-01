import { registry } from "@web/core/framework/registry";
import { standardFieldProps } from "../../standard_field_props";
import { _t } from "@web/core/data/l10n/translation";
import { Component, useProps } from "@odoo/owl";

export class ContactStatisticsField extends Component {
    static template = "web.ContactStatisticsField";
    props = useProps({
        ...standardFieldProps,
    });

    get list() {
        return this.props.record.data[this.props.name] || [];
    }
}

export const contactStatisticsField = {
    component: ContactStatisticsField,
    displayName: _t("Contact Statistics"),
    supportedTypes: ["json"],
};

registry.category("fields").add("contact_statistics", contactStatisticsField);

/** @odoo-module **/

import { Component, signal, t, useEffect, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Standalone picklist control for pharaccount.account.
 *
 * It shows the options of one picklist (``options="{'picklist': 'pharmacy_level'}"``)
 * that the current user may select, limited by the record type of the record.
 * The server decides what is selectable (groups and record type), so this control
 * only displays what it gets back.
 */
const pharaccountPicklistProps = {
    ...standardFieldProps,
    picklist: t.string().optional(),
};

export class PharaccountPicklistField extends Component {
    static template = "pharaccount.PicklistField";
    props = useProps(pharaccountPicklistProps);

    setup() {
        this.orm = useService("orm");
        this.options = signal([]);

        useEffect(
            () => {
                this.loadOptions();
            },
            () => [this.recordTypeId]
        );
    }

    get recordTypeId() {
        const recordType = this.props.record.data.record_type_id;
        return recordType ? recordType.id : false;
    }

    get currentValue() {
        const value = this.props.record.data[this.props.name];
        return value ? value.id : false;
    }

    get choices() {
        const choices = this.options().map((option) => ({
            id: option.id,
            label: option.label,
        }));
        // Keep the saved value visible even when it is no longer selectable,
        // so that opening an old record does not silently clear it.
        const current = this.props.record.data[this.props.name];
        if (current && !choices.some((choice) => choice.id === current.id)) {
            choices.unshift({ id: current.id, label: current.display_name, disabled: true });
        }
        return choices;
    }

    async loadOptions() {
        if (!this.props.picklist) {
            this.options.set([]);
            return;
        }
        const options = await this.orm.call(
            "pharaccount.picklist.value",
            "get_widget_options",
            [this.props.picklist, this.recordTypeId]
        );
        this.options.set(options);
    }

    onChange(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id) {
            this.props.record.update({ [this.props.name]: false });
            return;
        }
        const choice = this.choices.find((c) => c.id === id);
        this.props.record.update({
            [this.props.name]: { id, display_name: choice ? choice.label : "" },
        });
    }
}

export const pharaccountPicklistField = {
    component: PharaccountPicklistField,
    displayName: _t("Pharmacy picklist"),
    supportedTypes: ["many2one"],
    supportedOptions: [
        {
            label: _t("Picklist name"),
            name: "picklist",
            type: "string",
        },
    ],
    extractProps({ options }) {
        return { picklist: options.picklist };
    },
};

registry.category("fields").add("pharaccount_picklist", pharaccountPicklistField);

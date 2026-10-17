import { Component, useProps } from "@odoo/owl";

import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { CharField, charFieldProps } from "@web/views/fields/text/char/char_field";

export class ShortcutCharField extends Component {
    static template = "mail.ShortcutCharField";
    static components = { CharField };
    props = useProps({ ...charFieldProps });

    get charProps() {
        return {
            ...this.props,
            placeholder: _t("e.g. hello"),
        };
    }
}

registry.category("fields").add("shortcut", {
    component: ShortcutCharField,
});

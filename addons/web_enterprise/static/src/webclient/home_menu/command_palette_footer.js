import { Component, t, useProps } from "@odoo/owl";
import { isMacOS } from "@web/core/services/browser/feature_detection";

export class CommandPaletteFooter extends Component {
    static template = "web_enterprise.HomeMenu.CommandPalette.Footer";

    props = useProps({
        //prop added by the command palette
        switchNamespace: t.function().optional(),
    });

    setup() {
        this.controlKey = isMacOS() ? "COMMAND" : "CONTROL";
    }
}

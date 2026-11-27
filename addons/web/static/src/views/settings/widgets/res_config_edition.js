import { registry } from "@web/core/framework/registry";
import { session } from "@web/boot/session";
import { Setting } from "@web/views/form/setting/setting";

import { Component, useProps } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Widget in the settings that handles a part of the "About" section.
 * Contains info about the odoo version and copyrights.
 */
class ResConfigEdition extends Component {
    static template = "res_config_edition";
    static components = { Setting };
    props = useProps({
        ...standardWidgetProps,
    });

    setup() {
        this.serverVersion = session.server_version;
    }
}

export const resConfigEdition = {
    component: ResConfigEdition,
};

registry.category("view_widgets").add("res_config_edition", resConfigEdition);

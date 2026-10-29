import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/services/user";
import { isSystrayItemVisible } from "@web/webclient/navbar/systray_visibility";
import { PromoteStudioDialog } from "@web_enterprise/webclient/promote_studio/promote_studio_dialog";
import { _t } from "@web/core/data/l10n/translation";

import { Component } from "@odoo/owl";

export class PromoteStudioSystrayItem extends Component {
    static template = "web_enterprise.SystrayItem";

    setup() {
        this.dialog = useService("dialog");
    }

    _onClick() {
        this.dialog.add(PromoteStudioDialog, {
            title: _t("Odoo Studio - Add new fields to any view"),
        });
    }
}

export const promoteStudioSystrayItem = {
    Component: PromoteStudioSystrayItem,
    isDisplayed: () => user.isSystem && isSystrayItemVisible("studio"),
};

registry
    .category("systray")
    .add("PromoteStudioSystrayItem", promoteStudioSystrayItem, { sequence: 1 });

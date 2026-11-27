import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

/** Adds the action of this model to a page of the mobile navigation. */
export class MobileNavDialog extends Component {
    static template = "web_builder.MobileNavDialog";
    static components = { Dialog };

    props = useProps({
        actionId: t.number().optional(),
        pages: t.array(),
        icons: t.array(),
        onSaved: t.function(),
        close: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            name: "",
            pageId: this.props.pages[0]?.id || 0,
            icon: "",
            sequence: 10,
            saving: false,
        });
    }

    get canSave() {
        return Boolean(this.props.actionId && this.state.name.trim() && this.state.pageId) && !this.state.saving;
    }

    async save() {
        this.state.saving = true;
        try {
            await this.orm.create("mobile_web.mobile.page.actions", [{
                name: this.state.name.trim(),
                mobile_page: this.state.pageId,
                ir_action: this.props.actionId,
                svg_icon_href: this.state.icon ? `#${this.state.icon}` : false,
                sequence: Number(this.state.sequence) || 10,
            }]);
            this.props.onSaved();
            this.props.close();
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || "Error", {
                type: "danger",
                sticky: true,
            });
        } finally {
            this.state.saving = false;
        }
    }
}

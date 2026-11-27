import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { MobileFieldDialog } from "./mobile_field_dialog";
import { MobileNavDialog } from "./mobile_nav_dialog";

/**
 * Studio page "Mobile" of a model: what the mobile client shows of it.
 * Layouts and filters on mobile come in the next version (see mobile_config_design.md).
 */
export class MobileSection extends Component {
    static template = "web_builder.MobileSection";

    props = useProps({
        model: t.object(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = proxy({ loading: true, info: null });

        onWillStart(() => this.load(this.props.model));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                return this.load(nextProps.model);
            }
        });
    }

    async load(model) {
        this.state.loading = true;
        try {
            this.state.info = await this.orm.call("ir.model", "studio_mobile_infos", [model.model]);
        } finally {
            this.state.loading = false;
        }
    }

    /** Runs a call, shows its error, and reloads the page. */
    async run(callable) {
        try {
            await callable();
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || "Error", {
                type: "danger",
                sticky: true,
            });
        }
        await this.load(this.props.model);
    }

    get info() {
        return this.state.info;
    }

    get deviceOptions() {
        return [["mobile", "Mobile"], ["pc", "PC"], ["both", "Both"]];
    }

    setDevice(menu, value) {
        return this.run(() => this.orm.write("ir.ui.menu", [menu.id], { device_type: value }));
    }

    toggleCustomField(field, name, value) {
        return this.run(() => this.orm.write("mobile.custom.field", [field.id], { [name]: value }));
    }

    openField() {
        this.dialog.add(MobileFieldDialog, {
            modelId: this.info.model_id,
            onSaved: () => this.load(this.props.model),
        });
    }

    deleteField(field) {
        this.dialog.add(ConfirmationDialog, {
            body: `Remove the mobile field "${field.name}"? Its column is removed from the mobile list.`,
            confirm: () => this.run(() => this.orm.unlink("mobile.custom.field", [field.id])),
        });
    }

    openNav() {
        this.dialog.add(MobileNavDialog, {
            actionId: this.info.mobile_action_id,
            pages: this.info.pages,
            icons: this.info.icons,
            onSaved: () => this.load(this.props.model),
        });
    }

    deleteNav(item) {
        return this.run(() => this.orm.unlink("mobile_web.mobile.page.actions", [item.id]));
    }
}

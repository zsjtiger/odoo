import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { RecordTypeDialog } from "./record_type_dialog";

/**
 * Studio page "Record Types" of a model: enable the record types, manage the types,
 * their permissions per group, and the default type per group.
 */
export class RecordTypeSection extends Component {
    static template = "web_builder.RecordTypeSection";

    props = useProps({
        model: t.object(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = proxy({
            loading: true,
            info: null,
            expanded: null,
        });

        onWillStart(() => this.load(this.props.model));
        onWillUpdateProps((nextProps) => {
            if (nextProps.model.id !== this.props.model.id) {
                this.state.expanded = null;
                return this.load(nextProps.model);
            }
        });
    }

    async load(model) {
        this.state.loading = true;
        try {
            this.state.info = await this.orm.call("ir.model", "studio_record_type_infos", [model.model]);
        } finally {
            this.state.loading = false;
        }
    }

    /** Runs a server or ORM call, shows its error to the user, and reloads the page. */
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

    /** Permission rows of one type, with the group name */
    permissionsOf(type) {
        return this.info.permissions.filter((perm) => perm.record_type_id === type.id);
    }

    /** Groups that have no permission row on this type yet */
    addableGroups(type) {
        const used = new Set(this.permissionsOf(type).map((perm) => perm.group_id));
        return this.info.groups.filter(([id]) => !used.has(id));
    }

    isDefault(type, groupId) {
        return this.info.defaults.some((d) => d.record_type_id === type.id && d.group_id === groupId);
    }

    toggleExpanded(type) {
        this.state.expanded = this.state.expanded === type.id ? null : type.id;
    }

    enable() {
        return this.run(() =>
            this.orm.call("ir.model", "action_enable_record_type", [[this.info.model_id]])
        );
    }

    disable() {
        this.dialog.add(ConfirmationDialog, {
            body: "Records of every type keep their type, but no type can be used until record types are enabled again. Continue?",
            confirm: () =>
                this.run(() =>
                    this.orm.call("ir.model", "action_disable_record_type", [[this.info.model_id]])
                ),
        });
    }

    openType(type = null) {
        this.dialog.add(RecordTypeDialog, {
            info: this.info,
            type,
            onSaved: () => this.load(this.props.model),
        });
    }

    deleteType(type) {
        this.dialog.add(ConfirmationDialog, {
            body: `Delete the record type "${type.name}"? It cannot be deleted while records use it.`,
            confirm: () => this.run(() => this.orm.unlink("ir.record.type", [type.id])),
        });
    }

    setPermission(perm, field, value) {
        return this.run(() => this.orm.write("ir.record.type.permission", [perm.id], { [field]: value }));
    }

    addPermission(type, groupId) {
        return this.run(() =>
            this.orm.create("ir.record.type.permission", [{
                record_type_id: type.id,
                group_id: groupId,
                perm_read: true,
            }])
        );
    }

    removePermission(perm) {
        return this.run(() => this.orm.unlink("ir.record.type.permission", [perm.id]));
    }

    /** Makes this type the default of the group for the model, or clears it. */
    setDefault(type, groupId, checked) {
        return this.run(async () => {
            const model = this.info.model_id;
            if (checked) {
                const previous = this.info.defaults.filter((d) => d.group_id === groupId).map((d) => d.id);
                if (previous.length) {
                    await this.orm.unlink("ir.record.type.default", previous);
                }
                await this.orm.create("ir.record.type.default", [{
                    model_id: model,
                    group_id: groupId,
                    record_type_id: type.id,
                }]);
            } else {
                const ids = this.info.defaults
                    .filter((d) => d.group_id === groupId && d.record_type_id === type.id)
                    .map((d) => d.id);
                if (ids.length) {
                    await this.orm.unlink("ir.record.type.default", ids);
                }
            }
        });
    }
}

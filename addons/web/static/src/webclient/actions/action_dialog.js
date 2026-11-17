import { t, usePlugin, useProps } from "@odoo/owl";
import { useOwnDebugContext } from "@web/core/services/debug/debug_context";
import { DebugMenu } from "@web/core/services/debug/debug_menu";
import { DebugModePlugin } from "@web/core/services/debug_mode_plugin";
import { Dialog, dialogProps } from "@web/core/dialogs/dialog/dialog";

export class ActionDialog extends Dialog {
    static components = { ...Dialog.components, DebugMenu };
    static template = "web.ActionDialog";
    static propsSchema = {
        ...dialogProps,
        // ActionDialog renders `actionProps.ActionComponent` in place of the
        // default slot, so unlike the base Dialog it may receive no slots.
        // Override the required `dialogProps.slots` to make it optional.
        slots: t.any().optional(),
        withBodyPadding: t.boolean().optional(false),
    };
    actionProps = useProps({
        ActionComponent: t.any().optional(),
        actionProps: t.any().optional(),
        actionType: t.any().optional(),
    });

    debugMode = usePlugin(DebugModePlugin);

    setup() {
        super.setup();
        useOwnDebugContext();
    }
}

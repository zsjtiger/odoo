import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import mobile from "@web_enterprise/mobile_app/js/services/core";

export function shortcutItem() {
    const menu = useService("menu");
    const notification = useService("notification");

    return {
        type: "item",
        id: "web_enterprise.mobile_app.shortcut",
        description: _t("Add to Home Screen"),
        callback: () => {
            const currentAppMenu = menu.getCurrentApp();
            if (currentAppMenu) {
                const base64Icon = currentAppMenu.webIconData;
                mobile.methods.addHomeShortcut({
                    title: document.title,
                    shortcut_url: document.URL,
                    web_icon: base64Icon.substring(base64Icon.indexOf(",") + 1),
                });
            } else {
                notification.add(_t("No shortcut for Home Menu"));
            }
        },
        sequence: 100,
    };
}

export function switchAccountItem() {
    return {
        type: "item",
        id: "web_enterprise.mobile_app.switch",
        description: _t("Switch/Add Account"),
        callback: () => {
            mobile.methods.switchAccount();
        },
        sequence: 100,
    };
}

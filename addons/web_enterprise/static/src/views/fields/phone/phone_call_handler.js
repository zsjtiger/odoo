import { isMobileOS } from "@web/core/services/browser/feature_detection";
import { phoneCallHandlerRegistry } from "@web/core/components/phone/phone_call";
import { user } from "@web/core/services/user";
import { PhoneInstallDialog } from "@web_enterprise/views/fields/phone/phone_install_dialog";

phoneCallHandlerRegistry.add("phone_install_dialog", {
    isApplicable(env) {
        return !isMobileOS() && user.isSystem && !env.services.voip;
    },

    execute(env) {
        env.services.dialog.add(PhoneInstallDialog);
        return false;
    },
});

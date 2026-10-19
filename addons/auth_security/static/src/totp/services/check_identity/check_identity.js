import { patch } from "@web/core/utils/patch";
import { CheckIdentityForm } from "@web/core/services/session/check_identity";

patch(CheckIdentityForm.prototype, {
    async setup() {
        super.setup();
        this.authMethodTemplates = {
            ...this.authMethodTemplates,
            totp: {
                form: "auth_security.CheckIdentityFormTOTP",
                linkString: "auth_security.CheckIdentityLinkStringTOTP",
            },
        };
    },
});

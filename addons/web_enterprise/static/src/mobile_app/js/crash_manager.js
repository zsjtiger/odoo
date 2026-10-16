import { registry } from "@web/core/framework/registry";
import mobile from "@web_enterprise/mobile_app/js/services/core";

function mobileErrorHandler(env, error, originalError) {
    if (mobile.methods.crashManager) {
        error.originalError = originalError;
        mobile.methods.crashManager(error);
    }
}
registry
    .category("error_handlers")
    .add("web_enterprise.mobile_app.errorHandler", mobileErrorHandler, { sequence: 3 });

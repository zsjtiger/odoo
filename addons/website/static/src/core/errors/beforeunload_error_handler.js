import { browser } from "@web/core/services/browser/browser";
import { registry } from "@web/core/framework/registry";

const errorHandlerRegistry = registry.category("error_handlers");

let isUnloadingPage = false;
window.addEventListener("beforeunload", () => {
    isUnloadingPage = true;
    // restore after 10 seconds
    browser.setTimeout(() => (isUnloadingPage = false), 10000);
});

/**
 * Handles the errors trigger after the before unload event.
 *
 * @param {OdooEnv} env
 * @param {UncaughError} error
 * @returns {boolean}
 */
function beforeUnloadHandler(env, error) {
    if (isUnloadingPage) {
        error.event.preventDefault();
        return true;
    }
    return false;
}

errorHandlerRegistry.add("beforeUnloadHandler", beforeUnloadHandler, { sequence: 1 });

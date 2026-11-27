import { browser } from "@web/core/services/browser/browser";
import { rpcBus } from "@web/core/services/network/rpc";
import { registry } from "@web/core/framework/registry";
import { UPDATE_METHODS } from "@web/core/services/orm_plugin";

// reload the page if changes are being done to `res.company`

registry.category("services").add("reloadCompany", {
    dependencies: ["action"],
    start(env, { action }) {
        rpcBus.addEventListener("RPC:RESPONSE", (ev) => {
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "res.company" && UPDATE_METHODS.includes(method)) {
                if (!browser.localStorage.getItem("running_tour")) {
                    action.doAction("reload_context");
                }
            }
        });
    },
});

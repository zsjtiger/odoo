import { rpcBus } from "@web/core/services/network/rpc";
import { registry } from "@web/core/framework/registry";
import { currencies } from "@web/core/data/currency";
import { ORM, UPDATE_METHODS } from "@web/core/services/orm_plugin";
import { Plugin, useListener, usePlugin } from "@odoo/owl";
import { services } from "@web/core/framework/services";

export class CurrencyPlugin extends Plugin {
    orm = usePlugin(ORM);

    setup() {
        useListener(rpcBus, "RPC:RESPONSE", (ev) => {
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "res.currency" && UPDATE_METHODS.includes(method)) {
                this.reloadCurrencies();
            }
        });
    }

    /**
     * Reload the currencies (initially given in session_info)
     */
    async reloadCurrencies() {
        const result = await this.orm.call("res.currency", "get_all_currencies");
        for (const k in currencies) {
            delete currencies[k];
        }
        Object.assign(currencies, result);
    }
}

services.add(CurrencyPlugin);

/**
 * -----------------------------------------------------------------------------
 * @todo owl3 migration
 * temporary - to remove when all use of the currency service are removed
 * -----------------------------------------------------------------------------
 */
registry.category("services").add("currency", {
    dependencies: ["orm"],
    start() {
        return usePlugin(CurrencyPlugin);
    },
});

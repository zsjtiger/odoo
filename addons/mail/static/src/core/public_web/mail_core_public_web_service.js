import { registry } from "@web/core/framework/registry";

export const mailCorePublicWebService = {
    dependencies: ["mail.store"],
    /**
     * @param {import("@web/boot/env").OdooEnv}
     * @param {Partial<import("services").Services>} services
     */
    start(env, services) {
        services["mail.store"].ensureInitialized();
        services["mail.store"].messagingMenu.initializeCountersFetcher.fetch();
    },
};

registry.category("services").add("mail.core.public.web", mailCorePublicWebService);

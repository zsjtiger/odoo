import { DiscussClientAction } from "@mail/core/public_web/discuss_app/client_action";

import { whenReady } from "@odoo/owl";

import { MainComponentsContainer } from "@web/core/framework/main_components_container";
import { registry } from "@web/core/framework/registry";
import { mountComponent } from "@web/boot/env";

(async function boot() {
    await whenReady();

    const mainComponentsRegistry = registry.category("main_components");
    mainComponentsRegistry.add("DiscussClientAction", { Component: DiscussClientAction });

    await mountComponent(MainComponentsContainer, document.body, { name: "Discuss" });
    odoo.isReady = true;
})();

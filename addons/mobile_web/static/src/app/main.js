import { startWebClient } from "@web/boot/start";
import { registry } from "@web/core/framework/registry";
import { registerMobileServices } from "@mobile_web/app/services";
import { MobileWebClient } from "@mobile_web/app/webclient";
import "@mobile_web/pages/index";
import { asComponent } from "@mobile_web/core/env";

registerMobileServices(registry.category("services"));

startWebClient(asComponent(MobileWebClient));

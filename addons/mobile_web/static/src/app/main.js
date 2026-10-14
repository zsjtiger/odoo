import { startWebClient } from "@web/boot/start";
import { registry } from "@web/core/framework/registry";
import { mobileActionService } from "@mobile_web/actions/action_service";
import { MobileWebClient } from "@mobile_web/app/webclient";
import "@mobile_web/pages/index";

registry.category("services").add("mobileAction", mobileActionService);

startWebClient(MobileWebClient);

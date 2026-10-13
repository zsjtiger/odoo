import { startWebClient } from "@web/boot/start";
import { MobileWebClient } from "@mobile_web/webclient/webclient";
import "@mobile_web/pages/index";

startWebClient(MobileWebClient);

import { WebClient } from "@web/webclient/webclient";
import { EnterpriseNavBar } from "./navbar/navbar";

export class WebClientEnterprise extends WebClient {
    static components = {
        ...WebClient.components,
        NavBar: EnterpriseNavBar,
    };
}

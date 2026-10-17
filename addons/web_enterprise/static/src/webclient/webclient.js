import { WebClient } from "@web/webclient/webclient";
import { useService } from "@web/core/utils/hooks";
import { EnterpriseNavBar } from "./navbar/navbar";

export class WebClientEnterprise extends WebClient {
    static components = {
        ...WebClient.components,
        NavBar: EnterpriseNavBar,
    };
    setup() {
        super.setup();
        this.hm = useService("home_menu");
    }
    _loadDefaultApp() {
        // Land on the first app as the Community edition does, the app launcher (waffle button) stays one click away
        if (this.menuService.getMenu("root").children.length) {
            return super._loadDefaultApp();
        }
        return this.hm.toggle(true);
    }
}

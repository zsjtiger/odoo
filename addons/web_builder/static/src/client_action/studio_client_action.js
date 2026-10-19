import { render } from "@web/core/owl/utils";
import { registry } from "@web/core/framework/registry";
import { user as originalUser } from "@web/core/services/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { computeAppsAndMenuItems } from "@web/webclient/menus/menu_helpers";

import { AppCreator } from "../app_creation/app_creator/app_creator";
import { ModelDesigner } from "./model_designer/model_designer";
import { Editor } from "../editors/editor/editor";
import { StudioNavbar } from "./navbar/navbar";
import { StudioHomeMenu } from "../home_menu/studio/studio_home_menu";

import { Component, onWillStart, onMounted, onPatched, onWillUnmount, useProps } from "@odoo/owl";

export class StudioClientAction extends Component {
    static template = "web_builder.StudioClientAction";
    static target = "fullscreen";
    static components = {
        StudioNavbar,
        StudioHomeMenu,
        Editor,
        AppCreator,
        ModelDesigner,
    };

    props = useProps(standardActionServiceProps);

    setup() {
        const homemenuConfig = JSON.parse(originalUser.settings?.homemenu_config || "null");
        this.studio = useService("studio");
        useBus(this.studio.bus, "UPDATE", () => {
            render(this);
        });

        this.menus = useService("menu");
        this.actionService = useService("action");
        let apps = computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps;
        if (homemenuConfig) {
            reorderApps(apps, homemenuConfig);
        }
        this.homeMenuProps = {
            apps: apps,
        };
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => {
            apps = computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps;
            if (homemenuConfig) {
                reorderApps(apps, homemenuConfig);
            }
            this.homeMenuProps = {
                apps: apps,
            };
            render(this);
        });

        onWillStart(async () => {
            await this.studio.ready;
            // Opened from the Studio app menu: there is no mode yet, start on the app picker
            if (!this.studio.mode) {
                this.studio.setParams({ mode: this.studio.MODES.HOME_MENU });
            }
        });
        onMounted(() => {
            document.body.classList.add("o_in_studio");
            this.studio.pushState();
        });
        onPatched(() => this.studio.pushState());
        onWillUnmount(() => document.body.classList.remove("o_in_studio"));
    }

    async onNewAppCreated({ action_id, menu_id }) {
        await this.menus.reload();
        this.menus.setCurrentMenu(menu_id);
        const action = await this.actionService.loadAction(action_id);

        let initViewType = "form";
        if (!action.views.some((vTuple) => vTuple[1] === initViewType)) {
            initViewType = action.views[0][1];
        }
        this.studio.setParams({
            mode: this.studio.MODES.EDITOR,
            editorTab: "views",
            action,
            viewType: initViewType,
        });
    }
}

registry.category("lazy_components").add("StudioClientAction", StudioClientAction);
// force: true to bypass the studio lazy loading action next time and just use this one directly
registry.category("actions").add("studio", StudioClientAction, { force: true });

/**
 * Sorts the apps of the home menu according to the given order of xmlids.
 * Apps missing from the order come first, in their original order.
 * @param {Array} apps
 * @param {string[]} order
 */
function reorderApps(apps, order) {
    apps.sort((a, b) => {
        const aIndex = order.indexOf(a.xmlid);
        const bIndex = order.indexOf(b.xmlid);
        if (aIndex === -1 && bIndex === -1) {
            return apps.indexOf(a) - apps.indexOf(b);
        }
        if (aIndex === -1) {
            return -1;
        }
        if (bIndex === -1) {
            return 1;
        }
        return aIndex - bIndex;
    });
}

import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dropdown } from "@web/core/components/dropdown/dropdown";
import { DropdownItem } from "@web/core/components/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";
import { computeAppsAndMenuItems } from "@web/webclient/menus/menu_helpers";

/**
 * App launcher of the navbar: a search field, the apps as tiles and all the menu items
 * of all the apps as links. Both lists are filtered by the search.
 */
export class AppLauncher extends Component {
    static template = "web.NavBar.AppLauncher";
    static components = { Dropdown, DropdownItem };
    props = useProps({
        apps: t.array(),
        onSelect: t.function(),
        getHref: t.function(),
        isAvailable: t.function(),
    });

    setup() {
        this.menuService = useService("menu");
        this.state = proxy({ query: "" });
    }

    get query() {
        return this.state.query.trim().toLowerCase();
    }

    get filteredApps() {
        return this.props.apps.filter((app) => this.matches(app.name));
    }

    get filteredItems() {
        const { menuItems } = computeAppsAndMenuItems(this.menuService.getMenuAsTree("root"));
        return menuItems.filter((item) => this.matches(`${item.label} ${item.parents}`));
    }

    matches(text) {
        return !this.query || text.toLowerCase().includes(this.query);
    }

    onInput(ev) {
        this.state.query = ev.target.value;
    }

    getIconClass(app) {
        return app.webIcon?.icon;
    }
}

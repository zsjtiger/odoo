import { click, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { getService } from "@web/../tests/web_test_helpers";

/**
 * Opens an app of the web client: from the Studio home (the app picker) when
 * it is displayed, otherwise from the apps dropdown of the navbar, the way the
 * Community edition does. The dropdown items are only rendered once opened.
 *
 * @param {string} xmlid xmlid of the menu of the app, e.g. "app_1"
 */
export async function openApp(xmlid) {
    if (document.querySelector(".o_studio_home_menu")) {
        const tile = `.o_studio_home_menu .o_app[data-menu-xmlid=${xmlid}]`;
        await waitFor(tile);
        document.querySelector(tile).click();
        await animationFrame();
        return;
    }
    // The web client may already be in the app (it lands on the first one)
    if (getService("menu").getCurrentApp()?.xmlid === xmlid) {
        return;
    }
    const selector = `.o-dropdown-item.o_app[data-menu-xmlid=${xmlid}]`;
    if (!document.querySelector(selector)) {
        await click(".o_navbar_apps_menu button");
    }
    await waitFor(selector);
    document.querySelector(selector).click();
    await animationFrame();
}

/**
 * The Studio home (picker of the app to customize) is opened from the Studio app.
 */
export async function openStudioHome() {
    await getService("action").doAction("web_builder.action_web_studio_home");
    await waitFor(".o_studio_home_menu");
}

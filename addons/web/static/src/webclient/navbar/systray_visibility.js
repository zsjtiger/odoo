import { user } from "@web/core/services/user";

/**
 * Whether the navigation bar item identified by `key` is shown for the current user.
 * Items are shown unless the user hid them in their preferences (`hidden_systray_items`).
 *
 * @param {string} key one of "ai", "messaging", "activity", "studio", "company"
 * @returns {boolean}
 */
export function isSystrayItemVisible(key) {
    return !(user.settings.hidden_systray_items || []).includes(key);
}

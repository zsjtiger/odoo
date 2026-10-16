/**
 * Sorts the apps in the home menu according to the given order, an array of xmlid strings.
 * Apps missing from the order keep their relative order and come first.
 *
 * @param {Array} apps
 * @param {Array<string>} order
 */
export function reorderApps(apps, order) {
    apps.sort((a, b) => {
        const aIndex = order.indexOf(a.xmlid);
        const bIndex = order.indexOf(b.xmlid);
        if (aIndex === -1 && bIndex === -1) {
            // if both items are not present, sort by original order
            return apps.indexOf(a) - apps.indexOf(b);
        }
        // not found items always before found ones
        if (aIndex === -1) {
            return -1;
        }
        if (bIndex === -1) {
            return 1;
        }
        return aIndex - bIndex; // sort by order array
    });
}

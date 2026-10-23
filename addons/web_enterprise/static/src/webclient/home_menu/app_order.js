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

/**
 * Returns a new order where the given app is placed right after the previous one,
 * or first when there is no previous app.
 *
 * @param {Array<string>} order xmlids in their current order
 * @param {string} xmlid xmlid of the moved app
 * @param {string} [previousXmlid] xmlid of the app it was dropped after
 * @returns {Array<string>}
 */
export function moveAppInOrder(order, xmlid, previousXmlid) {
    const newOrder = order.filter((id) => id !== xmlid);
    newOrder.splice(previousXmlid ? newOrder.indexOf(previousXmlid) + 1 : 0, 0, xmlid);
    return newOrder;
}

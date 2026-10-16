import { onRpc } from "@web/../tests/web_test_helpers";

/**
 * The subscription service reads the expiration date and reason from the database when it
 * starts for admins and internal users. Answers those reads from a fixed sequence: the first
 * call gets the first value, the following ones get the next values, then the last one.
 *
 * @param {Object} params
 * @param {string|string[]} params.date
 * @param {string|string[]} params.reason
 */
export function mockExpirationParams({ date, reason }) {
    const dates = [date].flat();
    const reasons = [reason].flat();
    let dateCount = 0;
    let reasonCount = 0;
    onRpc("get_str", ({ args }) => {
        if (args[0] === "database.expiration_date") {
            return dates[Math.min(dateCount++, dates.length - 1)];
        }
        if (args[0] === "database.expiration_reason") {
            return reasons[Math.min(reasonCount++, reasons.length - 1)];
        }
    });
}
